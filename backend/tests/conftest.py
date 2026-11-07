"""Fixtures de pruebas: base ``riego_test`` migrada con Alembic y sesión por test con rollback.

- La URL sale de ``TEST_DATABASE_URL`` (por defecto ``postgres`` local sobre ``riego_test``).
  Se usa un rol dueño para migrar; las sesiones de la app corren con ``SET LOCAL ROLE riego_app``
  para probar con los mismos privilegios y RLS que en producción.
- Cada test corre dentro de una transacción que se deshace al final; los ``commit()`` de la app
  solo liberan un SAVEPOINT (``join_transaction_mode="create_savepoint"``).
"""

from __future__ import annotations

import os

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://postgres@localhost:5432/riego_test"
)

# Debe ir antes de importar app.*: las variables del entorno tienen prioridad sobre backend/.env.
os.environ.update(
    {
        "APP_ENV": "test",
        "DEBUG": "false",
        "DATABASE_URL": TEST_DATABASE_URL,
        "DATABASE_URL_MIGRACIONES": TEST_DATABASE_URL,
        "DB_POOL": "queue",
        "JWT_SECRET": "secreto-de-pruebas-que-no-se-usa-en-ningun-otro-lado-0123456789",
        "COOKIE_SECURE": "false",
        "FRONTEND_URL": "http://localhost:5173",
        "CORS_ORIGINS": "",
        "SMTP_HOST": "",
        "SCHEDULER_ENABLED": "false",
    }
)

from collections.abc import Iterator  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import Connection, Engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db.session import crear_engine, get_db, normalizar_url  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
ROLES_SUPABASE = ("anon", "authenticated")


def alembic_config(url: str = TEST_DATABASE_URL) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["url"] = url
    cfg.attributes["configurar_logging"] = False
    return cfg


def _es_servidor_local(url) -> bool:
    return url.host in ("localhost", "127.0.0.1", "::1")


def _preparar_servidor(url_texto: str) -> None:
    """Crea la base de pruebas si falta y, solo en un servidor local, los roles de Supabase."""
    url = normalizar_url(url_texto)
    mantenimiento = crear_engine(url.set(database="postgres"), modo_pool="null",
                                 isolation_level="AUTOCOMMIT")
    try:
        with mantenimiento.connect() as conexion:
            existe = conexion.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": url.database}
            ).first()
            if not existe:
                conexion.exec_driver_sql(
                    f'CREATE DATABASE "{url.database}" ENCODING \'UTF8\' TEMPLATE template0'
                )
            if _es_servidor_local(url):
                # Simula los roles de Supabase para probar que no reciben privilegios.
                for rol in ROLES_SUPABASE:
                    conexion.exec_driver_sql(
                        f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{rol}') "
                        f"THEN CREATE ROLE {rol} NOLOGIN; END IF; END $$"
                    )
    finally:
        mantenimiento.dispose()


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    if make_url(TEST_DATABASE_URL).database in ("riego_dev", "postgres"):
        raise RuntimeError("TEST_DATABASE_URL no puede apuntar a la base de desarrollo")
    _preparar_servidor(TEST_DATABASE_URL)
    command.upgrade(alembic_config(), "head")
    motor = crear_engine(TEST_DATABASE_URL, modo_pool="queue")
    yield motor
    motor.dispose()


@pytest.fixture
def conexion(engine: Engine) -> Iterator[Connection]:
    """Conexión del dueño dentro de una transacción que se deshace al terminar el test."""
    with engine.connect() as con:
        transaccion = con.begin()
        try:
            yield con
        finally:
            transaccion.rollback()


@pytest.fixture
def db(conexion: Connection) -> Iterator[Session]:
    """Sesión de la app con los privilegios de ``riego_app`` (RLS incluido)."""
    conexion.exec_driver_sql("SET LOCAL ROLE riego_app")
    sesion = Session(bind=conexion, join_transaction_mode="create_savepoint",
                     autoflush=False, expire_on_commit=False)
    try:
        yield sesion
    finally:
        sesion.close()


@pytest.fixture
def db_dueno(conexion: Connection) -> Iterator[Session]:
    """Sesión con el rol dueño (preparar datos que la app no puede escribir).

    Comparte la conexión con ``db``: no combinar ambas en el mismo test.
    """
    sesion = Session(bind=conexion, join_transaction_mode="create_savepoint",
                     autoflush=False, expire_on_commit=False)
    try:
        yield sesion
    finally:
        sesion.close()


@pytest.fixture
def app(db: Session):
    from app.main import create_app

    aplicacion = create_app()

    def _get_db_prueba() -> Iterator[Session]:
        yield db

    aplicacion.dependency_overrides[get_db] = _get_db_prueba
    return aplicacion


@pytest.fixture
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as cliente:
        yield cliente
