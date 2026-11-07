"""Migraciones: subir y bajar completas, y el esquema coincide con los modelos."""

from __future__ import annotations

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Engine, text

import app.models  # noqa: F401
from app.db.base import ESQUEMA, Base
from tests.conftest import alembic_config


def _tablas(engine: Engine) -> set[str]:
    with engine.connect() as con:
        filas = con.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname = :e"), {"e": ESQUEMA}
        )
        return {f.tablename for f in filas}


def _version(engine: Engine) -> str | None:
    with engine.connect() as con:
        return con.execute(text(f"SELECT version_num FROM {ESQUEMA}.alembic_version")).scalar()


def test_esquema_en_head_con_todas_las_tablas(engine: Engine):
    assert _version(engine) == "0002"
    esperadas = {t.name for t in Base.metadata.sorted_tables}
    assert len(esperadas) == 32
    assert _tablas(engine) == esperadas | {"alembic_version"}


def test_modelos_y_migracion_coinciden(engine: Engine):
    with engine.connect() as con:
        contexto = MigrationContext.configure(
            con,
            opts={
                "include_schemas": True,
                "include_name": lambda nombre, tipo, _p: tipo != "schema" or nombre == ESQUEMA,
                "version_table_schema": ESQUEMA,
                "compare_type": True,
                "compare_server_default": True,
            },
        )
        diferencias = compare_metadata(contexto, Base.metadata)
    assert diferencias == []


def test_downgrade_base_y_upgrade_head(engine: Engine):
    cfg = alembic_config()
    engine.dispose()  # sin conexiones del pool abiertas durante el DDL
    try:
        command.downgrade(cfg, "base")
        assert _tablas(engine) == {"alembic_version"}
        assert _version(engine) is None
        with engine.connect() as con:
            tipos = con.execute(
                text(
                    "SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace "
                    "WHERE n.nspname = :e AND t.typtype = 'e'"
                ),
                {"e": ESQUEMA},
            ).scalar()
            funciones = con.execute(
                text(
                    "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                    "WHERE n.nspname = :e"
                ),
                {"e": ESQUEMA},
            ).scalar()
        assert tipos == 0
        assert funciones == 0
    finally:
        command.upgrade(cfg, "head")
    assert _version(engine) == "0002"
    assert len(_tablas(engine)) == 33
