"""Código más nuevo que la BD (migraciones sin aplicar): aviso al arrancar, /health y 503 claro."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import ProgrammingError

from app.api.manejadores import MENSAJE_ESQUEMA_DESACTUALIZADO, registrar_manejadores
from app.db.version_esquema import comprobar, revision_esperada
from app.main import verificar_migraciones


class _BdEnRevision:
    """Conexión falsa que responde una revisión fija de riego.alembic_version."""

    def __init__(self, revision: str | None, falla: bool = False):
        self.revision, self.falla = revision, falla

    def execute(self, *_a, **_k):
        if self.falla:
            raise RuntimeError("permiso denegado")
        revision = self.revision

        class _Resultado:
            def scalar(self):
                return revision

        return _Resultado()

    def rollback(self):
        pass


def test_la_bd_de_pruebas_esta_al_dia(db):
    version = comprobar(db)
    assert version.estado == "al_dia"
    assert version.bd == version.esperada == revision_esperada()


def test_detecta_migraciones_pendientes_y_explica_que_hacer():
    version = comprobar(_BdEnRevision("0001"))
    assert (version.estado, version.bd) == ("pendientes", "0001")
    assert "alembic upgrade head" in version.mensaje and revision_esperada() in version.mensaje


def test_sin_poder_leer_la_version_queda_desconocido():
    assert comprobar(_BdEnRevision(None, falla=True)).estado == "desconocido"


def test_al_arrancar_avisa_en_el_log_si_faltan_migraciones(caplog):
    with caplog.at_level(logging.ERROR, logger="app"):
        verificar_migraciones(_BdEnRevision("0001"))
    assert "alembic upgrade head" in caplog.text


def test_health_informa_migraciones_y_queda_degradado_si_faltan(app, client):
    from app.db.session import get_db

    assert client.get("/api/v1/health").json()["migraciones"] == "al_dia"

    class SesionAtrasada(_BdEnRevision):
        def execute(self, consulta, *a, **k):
            if "alembic_version" in str(consulta):
                return super().execute()
            return _BdEnRevision("1").execute()  # SELECT 1 y el rol: responden algo

    app.dependency_overrides[get_db] = lambda: SesionAtrasada("0001")
    cuerpo = client.get("/api/v1/health").json()
    assert cuerpo["migraciones"] == "pendientes"
    assert cuerpo["status"] == "degradado"


def test_columna_inexistente_responde_503_con_mensaje_claro():
    class ColumnaInexistente(Exception):
        sqlstate = "42703"

    aplicacion = FastAPI()
    registrar_manejadores(aplicacion)

    @aplicacion.get("/falla")
    def falla():
        raise ProgrammingError("SELECT cronograma.anulado_at", {}, ColumnaInexistente())

    @aplicacion.get("/otro")
    def otro():
        raise RuntimeError("otra cosa")

    with TestClient(aplicacion, raise_server_exceptions=False) as cliente:
        r = cliente.get("/falla")
        assert r.status_code == 503 and r.json()["detail"] == MENSAJE_ESQUEMA_DESACTUALIZADO
        assert cliente.get("/otro").status_code == 500
