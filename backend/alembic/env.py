"""Entorno de Alembic para el esquema ``riego``.

- URL: ``config.attributes["url"]`` (tests) o ``DATABASE_URL_MIGRACIONES`` / ``DATABASE_URL``.
  Usar el puerto 5432 con el rol dueño: la conexión directa ``db.<ref>.supabase.co`` (solo IPv6
  sin el complemento IPv4) o el *Session pooler* ``aws-0-<region>.pooler.supabase.com:5432``
  (IPv4). El pooler en modo transacción (6543) no sirve para DDL: se rechaza.
- Sin conexión posible: ``alembic upgrade head --sql`` genera el SQL para el editor de Supabase.
- La tabla ``alembic_version`` vive en ``riego`` (Supabase solo publica ``public``).
- Solo se comparan objetos del esquema ``riego``.
"""

from __future__ import annotations

import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

import app.models  # noqa: F401  (registra las tablas)
from app.core.config import settings
from app.db.base import ESQUEMA, Base
from app.db.session import PUERTO_POOLER_TRANSACCION, crear_engine, normalizar_url

config = context.config

if config.config_file_name is not None and config.attributes.get("configurar_logging", True):
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def _url():
    return normalizar_url(config.attributes.get("url") or settings.url_migraciones)


def _incluir_nombre(nombre, tipo, padres) -> bool:
    if tipo == "schema":
        return nombre == ESQUEMA
    return True


OPCIONES = dict(
    target_metadata=target_metadata,
    version_table_schema=ESQUEMA,
    include_schemas=True,
    include_name=_incluir_nombre,
    compare_type=True,
    compare_server_default=True,
)


def run_migrations_offline() -> None:
    # En Windows la salida redirigida usa cp1252: el SQL (con "Ñ") debe salir en UTF-8 para
    # pegarlo en el editor de Supabase.
    if config.output_buffer is None and (sys.stdout.encoding or "").lower() not in ("utf-8", "utf8"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    context.configure(
        url=_url().render_as_string(hide_password=False),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **OPCIONES,
    )
    with context.begin_transaction():
        context.execute(f"CREATE SCHEMA IF NOT EXISTS {ESQUEMA}")
        context.run_migrations()


def run_migrations_online() -> None:
    conexion_externa = config.attributes.get("connection")
    if conexion_externa is not None:
        _migrar(conexion_externa)
        return

    url = _url()
    if url.port == PUERTO_POOLER_TRANSACCION:
        raise SystemExit(
            "DATABASE_URL_MIGRACIONES usa el puerto 6543 (pooler en modo transacción), que no "
            "admite DDL de forma fiable. Usa la conexión directa (db.<ref>.supabase.co:5432) o el "
            "Session pooler (aws-0-<region>.pooler.supabase.com:5432), o genera el SQL con "
            "`alembic upgrade head --sql`."
        )
    engine = crear_engine(url, modo_pool="null")
    with engine.connect() as conexion:
        _migrar(conexion)
    engine.dispose()


def _migrar(conexion) -> None:
    # El esquema debe existir antes de que Alembic cree riego.alembic_version.
    conexion.execute(text(f"CREATE SCHEMA IF NOT EXISTS {ESQUEMA}"))
    conexion.commit()
    context.configure(connection=conexion, **OPCIONES)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
