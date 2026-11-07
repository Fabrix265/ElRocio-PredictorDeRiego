"""Configuración de la conexión (pooler de Supabase) y salud del servicio."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.session import crear_engine, normalizar_url, opciones_engine

POOLER = "postgresql://riego_app.ref:clave@aws-0-sa-east-1.pooler.supabase.com:6543/postgres"
DIRECTA = "postgresql://postgres:clave@db.ref.supabase.co:5432/postgres"


def test_normaliza_driver_psycopg():
    assert normalizar_url(POOLER).drivername == "postgresql+psycopg"
    assert normalizar_url("postgres://u@h/db").drivername == "postgresql+psycopg"


def test_url_vacia_da_error_claro():
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        normalizar_url("")


def test_pooler_6543_sin_prepared_statements_ni_pool():
    connect_args, opciones = opciones_engine(normalizar_url(POOLER), "auto")
    assert connect_args["prepare_threshold"] is None
    assert opciones["poolclass"] is NullPool
    engine = crear_engine(POOLER, modo_pool="auto")
    assert isinstance(engine.pool, NullPool)
    engine.dispose()


def test_conexion_directa_usa_pool_salvo_db_pool_null():
    connect_args, opciones = opciones_engine(normalizar_url(DIRECTA), "auto")
    assert "prepare_threshold" not in connect_args and "poolclass" not in opciones
    connect_args, opciones = opciones_engine(normalizar_url(DIRECTA), "null")
    assert connect_args["prepare_threshold"] is None and opciones["poolclass"] is NullPool


def test_produccion_exige_configuracion_segura():
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None, app_env="production", jwt_secret="corto",
                 database_url=DIRECTA, frontend_url="https://riego.ejemplo.pe")
    ok = Settings(_env_file=None, app_env="production", jwt_secret="x" * 40, debug=False,
                  cookie_secure=True, cors_origins="", database_url=POOLER,
                  database_url_migraciones=DIRECTA, frontend_url="https://riego.ejemplo.pe")
    assert ok.cors_origin_list == ["https://riego.ejemplo.pe"]
    assert make_url(ok.url_migraciones).port == 5432
    with pytest.raises(ValueError, match="COOKIE_SECURE"):
        Settings(_env_file=None, app_env="production", jwt_secret="x" * 40, debug=False,
                 cookie_secure=False, database_url=POOLER, frontend_url="https://riego.ejemplo.pe")


def test_health_con_bd(client):
    respuesta = client.get("/api/v1/health")
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["status"] == "ok" and cuerpo["bd"] == "ok"
    assert cuerpo["entorno"] == "test" and cuerpo["modelo"] is None
    assert cuerpo["app"]


def test_health_sin_bd(app, client):
    from app.db.session import get_db

    class SesionRota:
        def execute(self, *_a, **_k):
            raise OSError("sin conexión")

        def rollback(self):
            pass

    app.dependency_overrides[get_db] = lambda: SesionRota()
    respuesta = client.get("/api/v1/health")
    assert respuesta.status_code == 503
    assert respuesta.json()["bd"] == "error"
