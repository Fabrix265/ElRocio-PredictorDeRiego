"""Entorno de Alembic para el esquema ``riego``.

- URL: ``config.attributes["url"]`` (tests) o ``DATABASE_URL_MIGRACIONES`` / ``DATABASE_URL``.
  Usar el puerto 5432 (conexión directa, rol dueño); el pooler 6543 no sirve para DDL.
- La tabla ``alembic_version`` vive en ``riego`` (Supabase solo publica ``public``).
- Solo se comparan objetos del esquema ``riego``.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool, text

import app.models  # noqa: F401  (registra las tablas)
from app.core.config import settings
from app.db.base import ESQUEMA, Base
from app.db.session import normalizar_url

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
    from sqlalchemy import create_engine

    conexion_externa = config.attributes.get("connection")
    if conexion_externa is not None:
        _migrar(conexion_externa)
        return

    engine = create_engine(_url(), poolclass=pool.NullPool)
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
