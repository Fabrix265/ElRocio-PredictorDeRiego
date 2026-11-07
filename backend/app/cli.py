"""Comandos de administración: ``python -m app.cli <comando>`` (desde ``backend/``).

- ``configurar-rol-app``: da LOGIN y contraseña al rol ``riego_app`` (lee RIEGO_APP_PASSWORD).
- ``verificar-seguridad-bd``: revisa RLS, políticas, privilegios y triggers del esquema ``riego``.

Ambos usan DATABASE_URL_MIGRACIONES (rol dueño, conexión directa 5432).
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable

from sqlalchemy import text

from app.core.config import settings
from app.db.seguridad import ROL_APP, verificar_seguridad
from app.db.session import crear_engine

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
            if not conexion.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROL_APP}).first():
                print(f"No existe el rol {ROL_APP}: ejecuta primero `alembic upgrade head`.", file=sys.stderr)
                return 1
            # La contraseña se cifra (SCRAM-SHA-256) en el cliente con libpq: nunca viaja ni
            # queda en los logs del servidor en texto plano.
            pgconn = conexion.connection.driver_connection.pgconn
            verificador = pgconn.encrypt_password(
                password.encode("utf-8"), ROL_APP.encode(), b"scram-sha-256"
            ).decode("ascii")
            literal = verificador.replace("'", "''")
            conexion.exec_driver_sql(
                f"ALTER ROLE {ROL_APP} WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE "
                f"NOBYPASSRLS PASSWORD '{literal}'"
            )
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
