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


# --- La app debe conectarse como riego_app ------------------------------------

def test_problemas_rol_conexion(conexion):
    from app.db.seguridad import problemas_rol_conexion

    problemas = problemas_rol_conexion(conexion)  # dueño/superusuario local (postgres)
    assert any("no riego_app" in p for p in problemas)
    assert any("superusuario" in p for p in problemas)
    conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
    assert problemas_rol_conexion(conexion) == []


def _config_con_superusuario(**extra) -> Settings:
    from tests.conftest import TEST_DATABASE_URL

    return Settings(
        _env_file=None, jwt_secret="x" * 48, cookie_secure=True,
        database_url=TEST_DATABASE_URL, frontend_url="https://riego.example.com", **extra,
    )


def test_produccion_no_arranca_con_el_rol_dueno():
    from fastapi.testclient import TestClient

    from app.main import create_app

    aplicacion = create_app(_config_con_superusuario(app_env="production", debug=False))
    with pytest.raises(RuntimeError, match="riego_app"):
        with TestClient(aplicacion):
            pass


def test_desarrollo_avisa_si_el_rol_es_inseguro(caplog):
    from fastapi.testclient import TestClient

    from app.main import create_app

    aplicacion = create_app(_config_con_superusuario(app_env="development"))
    with caplog.at_level("WARNING", logger="app"):
        with TestClient(aplicacion) as cliente:
            assert cliente.get("/docs").status_code == 200  # arranca igual
    assert "no se conecta con un rol seguro" in caplog.text


def test_health_degradado_con_el_rol_dueno(db_dueno):
    from fastapi.testclient import TestClient

    from app.db.session import get_db
    from app.main import create_app

    aplicacion = create_app()
    aplicacion.dependency_overrides[get_db] = lambda: db_dueno
    with TestClient(aplicacion) as cliente:
        cuerpo = cliente.get("/api/v1/health").json()
    assert cuerpo["bd"] == "ok"
    assert (cuerpo["status"], cuerpo["rol_bd"]) == ("degradado", "inseguro")


def test_health_ok_informa_el_rol(client):
    assert client.get("/api/v1/health").json()["rol_bd"] == "ok"


def test_produccion_cors_solo_con_frontend_url():
    base = dict(_env_file=None, app_env="production", jwt_secret="x" * 40, debug=False,
                cookie_secure=True, database_url=POOLER, frontend_url="https://riego.ejemplo.pe")
    assert Settings(**base, cors_origins="https://riego.ejemplo.pe/").cors_origin_list == [
        "https://riego.ejemplo.pe/"
    ]
    with pytest.raises(ValueError, match="CORS_ORIGINS solo puede contener FRONTEND_URL"):
        Settings(**base, cors_origins="http://localhost:5173,http://127.0.0.1:5173")
    with pytest.raises(ValueError, match="COOKIE_SAMESITE"):
        Settings(**base, cookie_samesite="lax")


def test_cors_nunca_acepta_asterisco():
    with pytest.raises(ValueError, match=r"'\*'"):
        Settings(_env_file=None, cors_origins="*")
