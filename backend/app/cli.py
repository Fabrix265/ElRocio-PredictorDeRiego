"""Comandos de administración: ``python -m app.cli <comando>`` (desde ``backend/``).

- ``configurar-rol-app``: da LOGIN y contraseña al rol ``riego_app`` (lee RIEGO_APP_PASSWORD).
- ``verificar-seguridad-bd``: revisa RLS, políticas, privilegios y triggers del esquema ``riego``.
- ``crear-admin``: alta de un administrador (interactivo o con flags); audita ``usuario_creado``
  con actor "sistema".
- ``cargar-historico``: carga idempotente de ``ml/data/raw`` (meteo, Phytech, NDVI, riego) y
  recálculo de ``ambiente_diario``.
- ``recalcular-ambiente``: recalcula ``ambiente_diario`` desde las lecturas guardadas.

Los dos primeros usan DATABASE_URL_MIGRACIONES (rol dueño, conexión directa 5432); los demás usan
DATABASE_URL (rol ``riego_app``), igual que la aplicación.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.db.seguridad import ROL_APP, verificar_seguridad
from app.db.session import crear_engine, unidad_de_trabajo

LARGO_MINIMO_PASSWORD_ROL = 16

# nombre -> (función, configurador del subparser, ayuda). Otros módulos agregan comandos aquí.
COMANDOS: dict[str, tuple[Callable[[argparse.Namespace], int], Callable[[argparse.ArgumentParser], None], str]] = {}


def comando(nombre: str, ayuda: str, argumentos: Callable[[argparse.ArgumentParser], None] | None = None):
    def registrar(funcion: Callable[[argparse.Namespace], int]):
        COMANDOS[nombre] = (funcion, argumentos or (lambda _p: None), ayuda)
        return funcion

    return registrar


def _engine_migraciones():
    if not settings.url_migraciones:
        raise SystemExit("Falta DATABASE_URL_MIGRACIONES (o DATABASE_URL) en backend/.env")
    return crear_engine(settings.url_migraciones, modo_pool="null")


ATRIBUTOS_PROHIBIDOS = {
    "rolsuper": "SUPERUSER",
    "rolbypassrls": "BYPASSRLS",
    "rolcreaterole": "CREATEROLE",
    "rolcreatedb": "CREATEDB",
}


def atributos_de_mas(conexion, rol: str) -> list[str] | None:
    """Atributos prohibidos que tiene ``rol`` (``None`` si el rol no existe)."""
    fila = conexion.execute(
        text("SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = :r"),
        {"r": rol},
    ).first()
    if fila is None:
        return None
    return [nombre for columna, nombre in ATRIBUTOS_PROHIBIDOS.items() if getattr(fila, columna)]


def configurar_rol(conexion, rol: str, password: str) -> None:
    """``ALTER ROLE <rol> WITH LOGIN PASSWORD '<scram>'``.

    Solo LOGIN y contraseña: los demás atributos (NOSUPERUSER, NOBYPASSRLS...) ya los fija el
    CREATE ROLE de la migración 0001, y en Supabase el rol ``postgres`` no es superusuario, así que
    no puede escribir la cláusula NOSUPERUSER (ni siquiera para quitarla).
    """
    # La contraseña se cifra (SCRAM-SHA-256) en el cliente con libpq: nunca viaja ni queda en
    # los logs del servidor en texto plano.
    pgconn = conexion.connection.driver_connection.pgconn
    verificador = pgconn.encrypt_password(
        password.encode("utf-8"), rol.encode(), b"scram-sha-256"
    ).decode("ascii")
    literal = verificador.replace("'", "''")
    identificador = '"' + rol.replace('"', '""') + '"'
    conexion.exec_driver_sql(f"ALTER ROLE {identificador} WITH LOGIN PASSWORD '{literal}'")


@comando("configurar-rol-app", "Da LOGIN y contraseña al rol riego_app (lee RIEGO_APP_PASSWORD).")
def configurar_rol_app(_args: argparse.Namespace) -> int:
    password = os.environ.get("RIEGO_APP_PASSWORD") or (
        settings.riego_app_password.get_secret_value() if settings.riego_app_password else ""
    )
    if len(password) < LARGO_MINIMO_PASSWORD_ROL:
        print(
            f"Define RIEGO_APP_PASSWORD (mínimo {LARGO_MINIMO_PASSWORD_ROL} caracteres) "
            "en el entorno o en backend/.env.",
            file=sys.stderr,
        )
        return 2

    engine = _engine_migraciones()
    try:
        with engine.begin() as conexion:
            de_mas = atributos_de_mas(conexion, ROL_APP)
            if de_mas is None:
                print(f"No existe el rol {ROL_APP}: ejecuta primero `alembic upgrade head`.", file=sys.stderr)
                return 1
            if de_mas:
                # No se le da LOGIN a un rol con privilegios de más (se saltaría RLS o permisos).
                print(
                    f"El rol {ROL_APP} tiene atributos prohibidos ({', '.join(de_mas)}): "
                    "quítalos antes de darle LOGIN.",
                    file=sys.stderr,
                )
                return 1
            configurar_rol(conexion, ROL_APP, password)
    finally:
        engine.dispose()
    print(f"Rol {ROL_APP} configurado: LOGIN con la contraseña de RIEGO_APP_PASSWORD.")
    print("Usa ese usuario y contraseña en DATABASE_URL de la aplicación.")
    return 0


@comando("verificar-seguridad-bd", "Revisa RLS, políticas, privilegios y triggers del esquema riego.")
def verificar_seguridad_bd(_args: argparse.Namespace) -> int:
    engine = _engine_migraciones()
    try:
        with engine.connect() as conexion:
            problemas = verificar_seguridad(conexion)
    finally:
        engine.dispose()
    if problemas:
        print(f"Se encontraron {len(problemas)} problema(s) de seguridad:", file=sys.stderr)
        for problema in problemas:
            print(f"  - {problema}", file=sys.stderr)
        return 1
    print("Seguridad de la base de datos: OK (RLS, políticas, privilegios y triggers).")
    return 0


def _args_crear_admin(p: argparse.ArgumentParser) -> None:
    p.add_argument("--username", help="Nombre de usuario (minúsculas, 3 a 60 caracteres)")
    p.add_argument("--nombre", help="Nombre completo")
    p.add_argument("--correo", help="Correo (para recuperar la contraseña)")
    grupo = p.add_mutually_exclusive_group()
    grupo.add_argument("--password", help="Contraseña (si falta se pide sin mostrarla)")
    grupo.add_argument("--password-stdin", action="store_true",
                       help="Lee la contraseña de la entrada estándar (scripts)")
    p.add_argument("--temporal", action="store_true",
                   help="Obliga a cambiar la contraseña en el primer ingreso")


def _sesion_app():
    """Unidad de trabajo de la CLI (commit al terminar sin error)."""
    return unidad_de_trabajo()


def _pedir(valor: str | None, etiqueta: str) -> str:
    while not (valor or "").strip():
        valor = input(f"{etiqueta}: ")
    return valor.strip()


def _pedir_password(username: str) -> str:
    from app.core.security import errores_politica_password

    while True:
        password = getpass.getpass("Contraseña: ")
        errores = errores_politica_password(password, username)
        if errores:
            print(" ".join(errores), file=sys.stderr)
            continue
        if getpass.getpass("Repite la contraseña: ") != password:
            print("Las contraseñas no coinciden.", file=sys.stderr)
            continue
        return password


@comando("crear-admin", "Crea un usuario administrador (audita usuario_creado como \"sistema\").",
         _args_crear_admin)
def crear_admin(args: argparse.Namespace) -> int:
    from pydantic import TypeAdapter, ValidationError

    from app.core.errores import ErrorApp
    from app.models.enums import RolUsuario
    from app.schemas.usuarios import Correo, Username
    from app.services import usuario_service
    from app.services.contexto import SISTEMA

    try:
        username = TypeAdapter(Username).validate_python(_pedir(args.username, "Usuario"))
        nombre = _pedir(args.nombre, "Nombre completo")
        correo = TypeAdapter(Correo).validate_python(_pedir(args.correo, "Correo"))
    except ValidationError as error:
        mensajes = "; ".join(e["msg"].removeprefix("Value error, ") for e in error.errors())
        print(f"Datos no válidos: {mensajes}", file=sys.stderr)
        return 2
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = args.password or _pedir_password(username)

    datos = usuario_service.DatosUsuarioNuevo(
        username=username, nombre=nombre, correo=str(correo), rol=RolUsuario.admin, password=password
    )
    try:
        with _sesion_app() as db:
            usuario = usuario_service.crear(
                db, datos, actor=None, contexto=SISTEMA, debe_cambiar_password=args.temporal
            )
            usuario_id, usuario_nombre = usuario.id, usuario.username
    except ErrorApp as error:
        print(error.detail, file=sys.stderr)
        return 1
    print(f"Administrador creado: {usuario_nombre} (id {usuario_id}).")
    return 0


# --- Datos de campo (F2) ---------------------------------------------------------

def _args_cargar_historico(p: argparse.ArgumentParser) -> None:
    from app.services.carga_historica import FUENTES

    p.add_argument("--fuentes", default=",".join(FUENTES),
                   help=f"Fuentes separadas por coma (por defecto todas: {','.join(FUENTES)})")
    p.add_argument("--meteo", type=Path, help="data_metereologica.xlsx (def. la de ml/config/pipeline.yaml)")
    p.add_argument("--phytech", type=Path, help="data_phytech.xlsx (hojas Suelo_horario y Planta_diario)")
    p.add_argument("--ndvi", type=Path, help="Carpeta con NdviImages_*_area<id>.xlsx")
    p.add_argument("--riego", type=Path, help="Excel de riego con la hoja MOD5")
    p.add_argument("--reemplazar", action="store_true",
                   help="Turno-días de riego con contenido distinto: crea una versión nueva")


@comando("cargar-historico", "Carga idempotente de meteo, Phytech, NDVI y riego histórico (ml/data/raw).",
         _args_cargar_historico)
def cargar_historico(args: argparse.Namespace) -> int:
    from app.services.carga_historica import FUENTES, RutasHistorico
    from app.services.carga_historica import cargar_historico as cargar

    fuentes = tuple(f.strip() for f in args.fuentes.split(",") if f.strip())
    desconocidas = sorted(set(fuentes) - set(FUENTES))
    if desconocidas:
        print(f"Fuentes desconocidas: {', '.join(desconocidas)}", file=sys.stderr)
        return 2
    rutas = RutasHistorico.por_defecto()
    for nombre in ("meteo", "phytech", "ndvi", "riego"):
        if getattr(args, nombre):
            setattr(rutas, nombre, getattr(args, nombre))
    with _sesion_app() as db:
        resultado = cargar(db, rutas, fuentes=fuentes, reemplazar=args.reemplazar)
    print(f"{'Fuente':<10} {'Estado':<8} {'Filas':>8} {'Nuevas':>8} {'Actualiz.':>9} {'Sin camb.':>9} {'Conflictos':>10}")
    for f in resultado.fuentes:
        print(f"{f.fuente:<10} {f.estado:<8} {f.filas:>8} {f.nuevas:>8} {f.actualizadas:>9} "
              f"{f.omitidas:>9} {f.conflictos:>10}")
        for mensaje in f.mensajes:
            print(f"    - {mensaje}")
    a = resultado.ambiente
    print(f"ambiente_diario: {a.dias} días recalculados, {a.nuevas} nuevos, {a.actualizadas} "
          f"actualizados, {a.sin_cambios} sin cambios, {a.borradas} borrados")
    return 1 if resultado.con_error else 0


def _args_recalcular_ambiente(p: argparse.ArgumentParser) -> None:
    p.add_argument("--desde", type=_fecha, help="AAAA-MM-DD (sin --desde/--hasta: todos los días con datos)")
    p.add_argument("--hasta", type=_fecha, help="AAAA-MM-DD (incluido)")


def _fecha(texto: str):
    from datetime import date

    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise argparse.ArgumentTypeError(f"fecha no válida: {texto} (use AAAA-MM-DD)") from None


@comando("recalcular-ambiente", "Recalcula ambiente_diario desde las lecturas guardadas en la BD.",
         _args_recalcular_ambiente)
def recalcular_ambiente(args: argparse.Namespace) -> int:
    from datetime import timedelta

    from app.repositories import datos_campo as repo
    from app.services import ambiente_service
    from app.services.carga_historica import CODIGO_MODULO

    with _sesion_app() as db:
        modulo = repo.modulo_por_codigo(db, CODIGO_MODULO)
        fundo = repo.fundo_por_id(db, modulo.fundo_id)
        if args.desde is None and args.hasta is None:
            resultado = ambiente_service.recalcular_todo(db, fundo)
        else:
            if args.desde is None or args.hasta is None or args.desde > args.hasta:
                print("Indica --desde y --hasta (desde <= hasta).", file=sys.stderr)
                return 2
            dias = [args.desde + timedelta(days=i) for i in range((args.hasta - args.desde).days + 1)]
            resultado = ambiente_service.recalcular(db, fundo, dias)
    print(f"ambiente_diario: {resultado.dias} días, {resultado.nuevas} nuevos, {resultado.actualizadas} "
          f"actualizados, {resultado.sin_cambios} sin cambios, {resultado.borradas} borrados")
    return 0


def _args_ingestar(p: argparse.ArgumentParser) -> None:
    from app.services.ingesta_service import FUENTES

    p.add_argument("--fuentes", default=",".join(FUENTES),
                   help=f"Fuentes separadas por coma (por defecto todas: {','.join(FUENTES)})")
    p.add_argument("--desde", type=_fecha,
                   help="AAAA-MM-DD (sin --desde/--hasta: última fecha guardada − 3 días hasta ayer)")
    p.add_argument("--hasta", type=_fecha, help="AAAA-MM-DD (incluido; por defecto ayer)")


@comando("ingestar", "Descarga WeatherLink y Phytech (suelo, planta, NDVI, pronóstico) y recalcula "
         "ambiente_diario.", _args_ingestar)
def ingestar(args: argparse.Namespace) -> int:
    from app.core.logging import configurar_logging
    from app.core.tiempo import hoy_lima
    from app.models.enums import DisparoIngesta, EstadoIngesta
    from app.services import ingesta_service

    configurar_logging()
    try:
        fuentes = ingesta_service.validar_fuentes(f.strip() for f in args.fuentes.split(",") if f.strip())
    except ValueError as error:
        print(error, file=sys.stderr)
        return 2
    try:
        desde, hasta = ingesta_service.validar_rango(args.desde, args.hasta, hoy_lima())
    except ValueError as error:
        print(f"{error}.", file=sys.stderr)
        return 2
    with _sesion_app() as db:
        ids = [c.id for c in ingesta_service.crear_corridas(
            db, fuentes, disparo=DisparoIngesta.script, desde=desde, hasta=hasta)]
    corridas = ingesta_service.ejecutar_en_sesiones(ids)
    print(f"{'Fuente':<15} {'Estado':<8} {'Desde':<10} {'Hasta':<10} {'Nuevas':>7} {'Actualiz.':>9} "
          f"{'Sin camb.':>9} {'Duración':>9}")
    for c in corridas:
        print(f"{c.fuente:<15} {c.estado.value:<8} {c.desde!s:<10} {c.hasta!s:<10} {c.filas_nuevas:>7} "
              f"{c.filas_actualizadas:>9} {c.filas_omitidas:>9} {c.duracion_ms / 1000:>8.1f}s")
        for error in c.errores:
            print(f"    - {error.get('tipo')}: {error.get('mensaje')} ({error.get('endpoint') or '-'})")
    con_error = len(corridas) < len(ids) or any(c.estado != EstadoIngesta.ok for c in corridas)
    return 1 if con_error else 0


def _args_reprocesar(p: argparse.ArgumentParser) -> None:
    p.add_argument("--desde", type=_fecha, required=True, help="AAAA-MM-DD")
    p.add_argument("--hasta", type=_fecha, required=True, help="AAAA-MM-DD (incluido)")
    p.add_argument("--pisar-excel", action="store_true",
                   help="Reemplaza también las lecturas del Excel histórico de esos días con las de "
                        "WeatherLink (error conocido del Excel; máx. 31 días; queda en la auditoría)")


@comando("reprocesar-weatherlink", "Vuelve a derivar meteo_lectura (origen weatherlink) desde los "
         "payloads guardados con las reglas actuales de conversión y recalcula ambiente_diario.",
         _args_reprocesar)
def reprocesar_weatherlink(args: argparse.Namespace) -> int:
    from app.services import ingesta_service

    if args.desde > args.hasta:
        print("Indica --desde <= --hasta.", file=sys.stderr)
        return 2
    try:
        with _sesion_app() as db:
            r = ingesta_service.reprocesar_weatherlink(db, args.desde, args.hasta,
                                                       pisar_excel=args.pisar_excel)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(f"Días con payload guardado: {r.dias_con_crudo}; lecturas reprocesadas: {r.lecturas}")
    print(f"meteo_lectura: {r.conteo.nuevas} nuevas, {r.conteo.actualizadas} actualizadas, "
          f"{r.conteo.omitidas} sin cambios o protegidas (Excel histórico), {r.borradas} borradas "
          f"(etiquetas de la regla anterior)")
    if r.dias_sin_crudo:
        muestra = ", ".join(d.isoformat() for d in r.dias_sin_crudo[:10])
        extra = f" y {len(r.dias_sin_crudo) - 10} más" if len(r.dias_sin_crudo) > 10 else ""
        print(f"Días sin payload de WeatherLink (no se tocan): {muestra}{extra}")
    if r.ambiente is not None:
        a = r.ambiente
        print(f"ambiente_diario: {a.dias} días, {a.nuevas} nuevos, {a.actualizadas} actualizados, "
              f"{a.sin_cambios} sin cambios, {a.borradas} borrados")
    return 0


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Administración del backend de riego.")
    sub = parser.add_subparsers(dest="comando", required=True, metavar="comando")
    for nombre, (funcion, argumentos, ayuda) in COMANDOS.items():
        p = sub.add_parser(nombre, help=ayuda, description=ayuda)
        argumentos(p)
        p.set_defaults(funcion=funcion)
    return parser


def _salida_utf8() -> None:
    # En Windows, la salida redirigida (Git Bash, archivos) usa cp1252 por defecto.
    for flujo in (sys.stdout, sys.stderr):
        if not flujo.isatty() and (flujo.encoding or "").lower() != "utf-8":
            try:
                flujo.reconfigure(encoding="utf-8")
            except (AttributeError, ValueError):
                pass


def main(argv: list[str] | None = None) -> int:
    _salida_utf8()
    args = construir_parser().parse_args(argv)
    return args.funcion(args)


if __name__ == "__main__":
    raise SystemExit(main())
