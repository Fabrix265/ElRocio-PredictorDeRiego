"""Comandos de administración: ``python -m app.cli <comando>`` (desde ``backend/``).

- ``configurar-rol-app``: da LOGIN y contraseña al rol ``riego_app`` (lee RIEGO_APP_PASSWORD).
- ``verificar-seguridad-bd``: revisa RLS, políticas, privilegios y triggers del esquema ``riego``.
- ``crear-admin``: alta de un administrador (interactivo o con flags); audita ``usuario_creado``
  con actor "sistema".

Los dos primeros usan DATABASE_URL_MIGRACIONES (rol dueño, conexión directa 5432);
``crear-admin`` usa DATABASE_URL (rol ``riego_app``), igual que la aplicación.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from sqlalchemy import text

from app.core.config import settings
from app.db.seguridad import ROL_APP, verificar_seguridad
from app.db.session import crear_engine, nueva_sesion

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


@contextmanager
def _sesion_app() -> Iterator:
    db = nueva_sesion()
    try:
        yield db
    finally:
        db.close()


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
