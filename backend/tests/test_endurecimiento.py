"""Cabeceras de seguridad, redacción de logs, zona horaria, CLI crear-admin y tareas programadas."""

from __future__ import annotations

import io
import logging
import sys
from contextlib import contextmanager
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import cli
from app.core.config import Settings
from app.core.logging import REDACTADO, FiltroRedaccion, configurar_logging, redactar
from app.core.tiempo import a_lima, ahora_utc, hoy_lima
from app.models import Auditoria, NotificacionCorreo, Usuario
from app.models.enums import EstadoCorreo
from tests.conftest import API, login

LIMA = ZoneInfo("America/Lima")


# --- Cabeceras ----------------------------------------------------------------

def test_cabeceras_de_seguridad(client: TestClient):
    respuesta = client.get(f"{API}/health")
    assert respuesta.status_code == 200
    assert respuesta.headers["x-content-type-options"] == "nosniff"
    assert respuesta.headers["x-frame-options"] == "DENY"
    assert respuesta.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors 'none'" in respuesta.headers["content-security-policy"]
    assert respuesta.headers["cache-control"] == "no-store"
    assert "strict-transport-security" not in respuesta.headers  # solo en producción
    # También en errores.
    assert client.get(f"{API}/no-existe").headers["x-frame-options"] == "DENY"
    assert client.get(f"{API}/no-existe").json() == {"detail": "Recurso no encontrado"}


def test_produccion_hsts_y_sin_docs():
    from app.main import create_app

    config = Settings(
        _env_file=None,
        app_env="production",
        debug=False,
        jwt_secret="x" * 48,
        cookie_secure=True,
        database_url="postgresql://riego_app:clave@localhost:6543/postgres",
        frontend_url="https://riego.example.com",
    )
    with TestClient(create_app(config)) as cliente:
        for ruta in ("/docs", f"{API}/openapi.json"):
            respuesta = cliente.get(ruta)
            assert respuesta.status_code == 404
            assert respuesta.headers["strict-transport-security"].startswith("max-age=31536000")
        preflight = cliente.options(f"{API}/auth/login", headers={
            "Origin": "https://riego.example.com", "Access-Control-Request-Method": "POST",
        })
        assert preflight.headers["access-control-allow-origin"] == "https://riego.example.com"
        ajeno = cliente.options(f"{API}/auth/login", headers={
            "Origin": "https://malo.example", "Access-Control-Request-Method": "POST",
        })
        assert "access-control-allow-origin" not in ajeno.headers


def test_produccion_rechaza_configuracion_insegura():
    with pytest.raises(ValueError, match="JWT_SECRET"):
        Settings(_env_file=None, app_env="production", jwt_secret="corto",
                 database_url="postgresql://x@h/db", frontend_url="https://a.example")


# --- Logs ---------------------------------------------------------------------

@pytest.mark.parametrize(
    ("texto", "secreto"),
    [
        ('{"username": "ana", "password": "Secreta2026"}', "Secreta2026"),
        ("{'password_nueva': 'Secreta2026'}", "Secreta2026"),
        ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.abcdefgh", "eyJhbGci"),
        ("headers={'X-Api-Secret': 'wl-secreto-123'}", "wl-secreto-123"),
        ("GET https://api.weatherlink.com/v2/current/1?api-key=clave123&t=1", "clave123"),
        ("X-API-SECRET-KEY: phytech-999", "phytech-999"),
        ("cookie: rt=refresh-opaco-123", "refresh-opaco-123"),
        ("enlace http://x/restablecer#token=abcDEF123", "abcDEF123"),
        ("password=Secreta2026&otro=1", "Secreta2026"),
    ],
)
def test_redaccion_de_secretos(texto: str, secreto: str):
    redactado = redactar(texto)
    assert secreto not in redactado
    assert REDACTADO in redactado


def test_filtro_redacta_mensajes_argumentos_y_excepciones():
    salida = io.StringIO()
    handler = logging.StreamHandler(salida)
    handler.addFilter(FiltroRedaccion())
    logger = logging.getLogger("prueba.redaccion")
    logger.addHandler(handler)
    logger.propagate = False
    try:
        logger.warning("datos %s", {"password": "Secreta2026", "usuario": "ana"})
        try:
            raise RuntimeError("fallo con token=abc123xyz")
        except RuntimeError:
            logger.exception("error")
    finally:
        logger.removeHandler(handler)
    texto = salida.getvalue()
    assert "Secreta2026" not in texto and "abc123xyz" not in texto
    assert "ana" in texto and texto.count(REDACTADO) >= 2


def test_filtro_compatible_con_el_log_de_accesos_de_uvicorn():
    from uvicorn.logging import AccessFormatter

    salida = io.StringIO()
    handler = logging.StreamHandler(salida)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s',
                                         use_colors=False))
    handler.addFilter(FiltroRedaccion())
    logger = logging.getLogger("uvicorn.access.prueba")
    logger.addHandler(handler)
    logger.propagate = False
    logger.setLevel(logging.INFO)
    try:
        for ruta in ("/api/v1/health", "/x?api-key=clave123&t=1"):
            logger.info('%s - "%s %s HTTP/%s" %d', "127.0.0.1:5000", "GET", ruta, "1.1", 200)
    finally:
        logger.removeHandler(handler)
    lineas = salida.getvalue().splitlines()
    assert lineas[0] == '127.0.0.1:5000 - "GET /api/v1/health HTTP/1.1" 200 OK'
    assert "clave123" not in lineas[1] and REDACTADO in lineas[1] and lineas[1].endswith(" 200 OK")


def test_httpx_en_warning():
    configurar_logging()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING


# --- Zona horaria -------------------------------------------------------------

def test_hoy_lima_a_las_23_30():
    # 23:30 en Lima = 04:30 UTC del día siguiente: "hoy" sigue siendo el día de Lima.
    with time_machine.travel(datetime(2026, 11, 7, 23, 30, tzinfo=LIMA), tick=False):
        assert datetime.now(timezone.utc).date() == date(2026, 11, 8)
        assert hoy_lima() == date(2026, 11, 7)
        assert a_lima(ahora_utc()).hour == 23
    with time_machine.travel(datetime(2026, 11, 8, 0, 30, tzinfo=LIMA), tick=False):
        assert hoy_lima() == date(2026, 11, 8)


def test_a_lima_toma_naive_como_utc():
    assert a_lima(datetime(2026, 11, 8, 4, 30)).replace(tzinfo=None) == datetime(2026, 11, 7, 23, 30)


# --- CLI crear-admin ----------------------------------------------------------

@pytest.fixture
def cli_con_db(db: Session, monkeypatch):
    @contextmanager
    def _sesion():
        yield db

    monkeypatch.setattr(cli, "_sesion_app", _sesion)
    return db


def test_crear_admin_con_flags(cli_con_db: Session, client: TestClient, capsys):
    codigo = cli.main([
        "crear-admin", "--username", "Admin", "--nombre", "Administración", "--correo",
        "admin@example.com", "--password", "AdminSeguro2026",
    ])
    assert codigo == 0, capsys.readouterr().err
    assert "Administrador creado: admin" in capsys.readouterr().out
    admin = cli_con_db.scalars(select(Usuario).where(Usuario.username == "admin")).one()
    assert admin.rol.value == "admin" and admin.debe_cambiar_password is False
    fila = cli_con_db.scalars(select(Auditoria).where(Auditoria.accion == "usuario_creado")).one()
    assert fila.username == "sistema" and fila.usuario_id is None
    assert login(client, "admin", "AdminSeguro2026").status_code == 200

    # Duplicado y datos inválidos.
    assert cli.main(["crear-admin", "--username", "admin", "--nombre", "X", "--correo",
                     "otro@example.com", "--password", "AdminSeguro2026"]) == 1
    assert "Ya existe" in capsys.readouterr().err
    assert cli.main(["crear-admin", "--username", "admin2", "--nombre", "X", "--correo",
                     "no-es-correo", "--password", "AdminSeguro2026"]) == 2
    assert cli.main(["crear-admin", "--username", "admin3", "--nombre", "X", "--correo",
                     "a3@example.com", "--password", "corta"]) == 1
    assert "al menos 10 caracteres" in capsys.readouterr().err


def test_crear_admin_interactivo_y_por_stdin(cli_con_db: Session, monkeypatch, capsys):
    respuestas = iter(["root2", "Otra Admin", "root2@example.com"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(respuestas))
    claves = iter(["corta", "AdminSeguro2026", "distinta2026x", "AdminSeguro2026", "AdminSeguro2026"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda _prompt: next(claves))
    assert cli.main(["crear-admin"]) == 0
    assert "Las contraseñas no coinciden." in capsys.readouterr().err

    monkeypatch.setattr(sys, "stdin", io.StringIO("ClaveStdin2026\n"))
    assert cli.main(["crear-admin", "--username", "root3", "--nombre", "R3", "--correo",
                     "r3@example.com", "--password-stdin", "--temporal"]) == 0
    root3 = cli_con_db.scalars(select(Usuario).where(Usuario.username == "root3")).one()
    assert root3.debe_cambiar_password is True


# --- Tareas programadas -------------------------------------------------------

def test_programador_tiene_la_tarea_de_correos():
    from app.jobs.runner import INTERVALO_CORREOS_S, crear_programador

    programador = crear_programador(en_segundo_plano=True)
    trabajos = {t.id: t for t in programador.get_jobs()}
    assert set(trabajos) == {"enviar_correos", "limpiar_intentos"}
    assert trabajos["enviar_correos"].trigger.interval.total_seconds() == INTERVALO_CORREOS_S
    assert str(programador.timezone) == "America/Lima"


def test_tarea_enviar_correos(client: TestClient, crear_usuario, db: Session, mailer, monkeypatch):
    from app.jobs import tareas

    crear_usuario("yoli")
    client.post(f"{API}/auth/recuperar", json={"identificador": "yoli"})
    monkeypatch.setattr(db, "close", lambda: None)
    monkeypatch.setattr(tareas, "nueva_sesion", lambda: db)
    resultado = tareas.enviar_correos(mailer)
    assert resultado.enviados == 1
    assert db.scalars(select(NotificacionCorreo)).one().estado == EstadoCorreo.enviado
