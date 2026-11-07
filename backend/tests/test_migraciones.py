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
    assert _version(engine) == "0003"
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
    assert _version(engine) == "0003"
    assert len(_tablas(engine)) == 33


# --- SQL offline (alembic upgrade head --sql), p. ej. para el editor de Supabase --

def _sql_offline(rango: str, *, bajar: bool = False) -> str:
    import io
    import re

    from alembic.config import Config

    from tests.conftest import BACKEND, TEST_DATABASE_URL

    salida = io.StringIO()
    cfg = Config(str(BACKEND / "alembic.ini"), output_buffer=salida)
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["url"] = TEST_DATABASE_URL
    cfg.attributes["configurar_logging"] = False
    (command.downgrade if bajar else command.upgrade)(cfg, rango, sql=True)
    sql = salida.getvalue()
    # Se ejecuta dentro de la transacción del test: sin el BEGIN/COMMIT que agrega Alembic.
    sql = re.sub(r"(?m)^\s*(BEGIN|COMMIT)\s*;\s*$", "", sql)
    assert not re.search(r"(?im)^\s*(BEGIN|COMMIT|ROLLBACK)\s*;", sql)
    return sql


def test_sql_offline_lleva_los_valores_de_la_semilla():
    sql = _sql_offline("head")
    assert "VALUES (NULL" not in sql and "= NULL" not in sql
    assert "'AVO PERÚ S.A.C.'" in sql and "'ENSUEÑO 1'" in sql
    bajada = _sql_offline("0003:0001", bajar=True)
    assert "NULL" not in bajada
    assert "IN ('AVOPERU', 'TALSA')" in bajada


def test_sql_offline_corre_en_una_base_vacia_como_dueno_no_superusuario(conexion):
    """Como en Supabase (el dueño no es superusuario): el SQL generado crea todo el esquema con
    su seguridad, la semilla con valores, y el SQL de bajada la borra. Todo se deshace al final."""
    from app.db.seguridad import verificar_seguridad

    subida = _sql_offline("head")
    bajada = _sql_offline("0003:0001", bajar=True)
    crudo = conexion.connection.driver_connection  # psycopg: varias sentencias sin parámetros

    conexion.exec_driver_sql(f"DROP SCHEMA {ESQUEMA} CASCADE")
    conexion.exec_driver_sql("CREATE ROLE zz_dueno_offline NOLOGIN NOSUPERUSER CREATEROLE")
    conexion.exec_driver_sql("GRANT CREATE ON DATABASE riego_test TO zz_dueno_offline")
    conexion.exec_driver_sql("SET LOCAL ROLE zz_dueno_offline")
    crudo.execute(subida)

    assert conexion.execute(text(f"SELECT version_num FROM {ESQUEMA}.alembic_version")).scalar() == "0003"
    assert conexion.execute(text(f"SELECT count(*) FROM {ESQUEMA}.lote")).scalar() == 22
    assert conexion.execute(
        text(f"SELECT nombre FROM {ESQUEMA}.fundo WHERE codigo = 'EN01'")
    ).scalar() == "ENSUEÑO 1"
    conexion.exec_driver_sql("RESET ROLE")
    assert verificar_seguridad(conexion) == []

    conexion.exec_driver_sql("SET LOCAL ROLE zz_dueno_offline")
    crudo.execute(bajada)
    assert conexion.execute(text(f"SELECT count(*) FROM {ESQUEMA}.empresa")).scalar() == 0
    assert conexion.execute(text(f"SELECT count(*) FROM {ESQUEMA}.motivo_correccion")).scalar() == 0
