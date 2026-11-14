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
    assert _version(engine) == "0006"
    esperadas = {t.name for t in Base.metadata.sorted_tables}
    assert len(esperadas) == 33
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
    assert _version(engine) == "0006"
    assert len(_tablas(engine)) == 34


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
    bajada = _sql_offline("0006:0001", bajar=True)
    assert "= NULL" not in bajada
    assert "IN ('AVOPERU', 'TALSA')" in bajada


def test_sql_offline_corre_en_una_base_vacia_como_dueno_no_superusuario(conexion):
    """Como en Supabase (el dueño no es superusuario): el SQL generado crea todo el esquema con
    su seguridad, la semilla con valores, y el SQL de bajada la borra. Todo se deshace al final."""
    from app.db.seguridad import verificar_seguridad

    subida = _sql_offline("head")
    bajada = _sql_offline("0006:0001", bajar=True)
    crudo = conexion.connection.driver_connection  # psycopg: varias sentencias sin parámetros

    conexion.exec_driver_sql(f"DROP SCHEMA {ESQUEMA} CASCADE")
    conexion.exec_driver_sql("CREATE ROLE zz_dueno_offline NOLOGIN NOSUPERUSER CREATEROLE")
    conexion.exec_driver_sql("GRANT CREATE ON DATABASE riego_test TO zz_dueno_offline")
    conexion.exec_driver_sql("SET LOCAL ROLE zz_dueno_offline")
    crudo.execute(subida)

    assert conexion.execute(text(f"SELECT version_num FROM {ESQUEMA}.alembic_version")).scalar() == "0006"
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


def test_0005_libera_fecha_y_downgrade_no_borra_historial(conexion):
    import pytest
    from sqlalchemy.exc import DBAPIError, IntegrityError

    sentencia = "INSERT INTO riego.cronograma (modulo_id, fecha) VALUES (1, '2026-11-10') RETURNING id"
    primero = conexion.execute(text(sentencia)).scalar_one()
    with pytest.raises(IntegrityError), conexion.begin_nested():
        conexion.execute(text(sentencia))
    conexion.execute(text("UPDATE riego.cronograma SET anulado_at = now(), anulado_motivo = 'Prueba' WHERE id = :id"),
                     {"id": primero})
    segundo = conexion.execute(text(sentencia)).scalar_one()
    assert primero != segundo
    with pytest.raises(DBAPIError, match="módulo y fecha repetidos"), conexion.begin_nested():
        conexion.exec_driver_sql(_sql_offline("0005:0004", bajar=True))
    assert conexion.execute(text("SELECT count(*) FROM riego.cronograma WHERE id IN (:a, :b)"),
                            {"a": primero, "b": segundo}).scalar_one() == 2
    assert conexion.execute(text("SELECT anulado_motivo FROM riego.cronograma WHERE id = :id"),
                            {"id": primero}).scalar_one() == "Prueba"


def test_0006_siembra_parametros_de_la_planilla_y_baja_limpio(conexion):
    fila = conexion.execute(text(
        "SELECT activo, capacidad_campo, distancia_hileras_m, mangueras_por_hilera, fase_fenologica, "
        "modo_ventana, curvas->'3'->>'3' AS c3_03, agotamiento_por_fase->>'Crecimiento de fruta' AS d "
        "FROM riego.parametros_pulsos WHERE modulo_id = 1")).one()
    assert (fila.activo, fila.capacidad_campo, fila.distancia_hileras_m, fila.mangueras_por_hilera) == (True, 0.14, 6, 4)
    assert (fila.fase_fenologica, fila.modo_ventana, fila.c3_03, fila.d) == (
        "Crecimiento de fruta", "automatico_con_respaldo", "4", "0.05")
    total = conexion.execute(text("SELECT count(*) FROM riego.modulo")).scalar_one()
    assert conexion.execute(text("SELECT count(*) FROM riego.parametros_pulsos")).scalar_one() == total
    conexion.exec_driver_sql(_sql_offline("0006:0005", bajar=True))
    assert conexion.execute(text(
        "SELECT to_regclass('riego.parametros_pulsos') IS NULL AND NOT EXISTS (SELECT 1 FROM "
        "information_schema.columns WHERE table_schema = 'riego' AND column_name IN ('calculo_pulsos', 'plan_modelo'))"
    )).scalar_one()
