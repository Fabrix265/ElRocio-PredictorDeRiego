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
        # La suite no necesita backend/.env (todo lo fija este diccionario) y así corre también
        # donde el archivo no se puede leer.
        "RIEGO_SIN_ENV_FILE": "1",
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
        # Nunca las claves reales de backend/.env: los clientes HTTP se prueban con APIs falsas
        # (tests/apis_falsas.py) y, si algo intentara usar la configuración, falla sin red.
        "WEATHERLINK_API_KEY": "",
        "WEATHERLINK_API_SECRET": "",
        "WEATHERLINK_STATION_ID": "28494",
        "PHYTECH_API_KEY": "",
        "PHYTECH_API_SECRET": "",
        "PHYTECH_AREA_ID": "12537",
        "PHYTECH_PLOT_ID": "70208",
        "PHYTECH_PROJECT_ID": "907557",
        "INGESTA_HORA": "05:00",
    }
)

import functools  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from email.message import EmailMessage  # noqa: E402
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


# --- Usuarios, sesiones y correos ---------------------------------------------

PASSWORD_PRUEBA = "Riego2026segura"
API = "/api/v1"
CABECERA_FETCH = {"X-Requested-With": "fetch"}


@functools.lru_cache
def _hash_cacheado(password: str) -> str:
    # argon2id es lento a propósito: se reutiliza el hash entre tests (sal incluida, sigue válido).
    from app.core.security import hash_password

    return hash_password(password)


@pytest.fixture
def crear_usuario(db: Session):
    """Fábrica: ``crear_usuario("ana", rol="encargado", ...)`` inserta un usuario como riego_app."""
    from app.models import Usuario
    from app.models.enums import RolUsuario

    def _crear(
        username: str,
        *,
        rol: str | RolUsuario = RolUsuario.admin,
        password: str = PASSWORD_PRUEBA,
        activo: bool = True,
        debe_cambiar_password: bool = False,
        correo: str | None = None,
        nombre: str | None = None,
    ) -> Usuario:
        usuario = Usuario(
            username=username,
            nombre=nombre or f"Usuario {username}",
            correo=correo or f"{username}@example.com",
            rol=RolUsuario(rol),
            password_hash=_hash_cacheado(password),
            activo=activo,
            token_version=0,
            debe_cambiar_password=debe_cambiar_password,
        )
        db.add(usuario)
        db.commit()
        return usuario

    return _crear


def login(client: TestClient, username: str, password: str = PASSWORD_PRUEBA):
    """POST /auth/login; devuelve la respuesta (el cliente guarda la cookie ``rt``)."""
    return client.post(f"{API}/auth/login", json={"username": username, "password": password})


def token_de(client: TestClient, username: str, password: str = PASSWORD_PRUEBA) -> str:
    respuesta = login(client, username, password)
    assert respuesta.status_code == 200, respuesta.text
    return respuesta.json()["access_token"]


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def auth(client: TestClient, crear_usuario):
    """Crea un usuario con el rol pedido y devuelve las cabeceras con su access token."""

    def _auth(rol: str = "admin", username: str | None = None, **kwargs) -> dict[str, str]:
        username = username or f"{rol}_prueba"
        crear_usuario(username, rol=rol, **kwargs)
        return bearer(token_de(client, username, kwargs.get("password", PASSWORD_PRUEBA)))

    return _auth


class MailerFalso:
    """Guarda los correos en memoria (sustituye a SMTP en las pruebas)."""

    def __init__(self) -> None:
        self.enviados: list[EmailMessage] = []

    def enviar(self, mensaje: EmailMessage) -> None:
        self.enviados.append(mensaje)

    def texto(self, indice: int = -1) -> str:
        return self.enviados[indice].get_body(preferencelist=("plain",)).get_content()

    def html(self, indice: int = -1) -> str:
        return self.enviados[indice].get_body(preferencelist=("html",)).get_content()


class MailerQueFalla:
    def __init__(self) -> None:
        self.intentos = 0

    def enviar(self, mensaje: EmailMessage) -> None:
        self.intentos += 1
        raise ConnectionRefusedError("servidor SMTP caído (password=no-debe-verse)")


@pytest.fixture
def mailer() -> MailerFalso:
    return MailerFalso()
