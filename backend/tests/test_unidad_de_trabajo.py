"""Convención de transacciones: los servicios hacen flush y la unidad de trabajo confirma."""

from __future__ import annotations

from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.deps import DbSesion
from app.db import session as modulo_sesion
from app.db.session import get_db, unidad_de_trabajo


class SesionFalsa:
    def __init__(self, eventos: list[str]) -> None:
        self.eventos = eventos

    def commit(self) -> None:
        self.eventos.append("commit")

    def rollback(self) -> None:
        self.eventos.append("rollback")

    def close(self) -> None:
        self.eventos.append("close")


def _otra_dependencia(db: DbSesion) -> int:
    return id(db)


def _app(eventos: list[str]) -> FastAPI:
    app = FastAPI()

    def _db():
        yield SesionFalsa(eventos)

    app.dependency_overrides[get_db] = _db

    @app.get("/ok")
    def ok(db: DbSesion, id_dep: Annotated[int, Depends(_otra_dependencia)]) -> dict:
        eventos.append("endpoint")
        return {"misma_sesion": id(db) == id_dep}

    @app.get("/falla")
    def falla(db: DbSesion) -> dict:
        eventos.append("endpoint")
        raise RuntimeError("falla del servicio")

    return app


def test_endpoint_sin_error_confirma_una_vez_y_comparte_la_sesion():
    eventos: list[str] = []
    with TestClient(_app(eventos)) as cliente:
        respuesta = cliente.get("/ok")
    assert respuesta.status_code == 200
    assert respuesta.json() == {"misma_sesion": True}
    assert eventos == ["endpoint", "commit"]


def test_endpoint_con_error_deshace_y_no_confirma():
    eventos: list[str] = []
    with TestClient(_app(eventos), raise_server_exceptions=False) as cliente:
        respuesta = cliente.get("/falla")
    assert respuesta.status_code == 500
    assert eventos == ["endpoint", "rollback"]


def test_unidad_de_trabajo_de_cli_confirma_o_deshace(monkeypatch):
    eventos: list[str] = []
    monkeypatch.setattr(modulo_sesion, "nueva_sesion", lambda: SesionFalsa(eventos))
    with unidad_de_trabajo():
        pass
    assert eventos == ["commit", "close"]

    eventos.clear()
    with pytest.raises(ValueError), unidad_de_trabajo():
        raise ValueError("error en el comando")
    assert eventos == ["rollback", "close"]

    eventos.clear()
    externa = SesionFalsa(eventos)
    with unidad_de_trabajo(externa) as db:
        assert db is externa
    assert eventos == ["commit"]  # una sesión ajena no se cierra


def test_usuario_service_no_confirma_por_su_cuenta(db, monkeypatch):
    """Crear un usuario solo hace flush: el commit queda para la unidad de trabajo."""
    from app.models.enums import RolUsuario
    from app.services import usuario_service
    from app.services.contexto import SISTEMA

    llamadas: list[str] = []
    monkeypatch.setattr(db, "commit", lambda: llamadas.append("commit"))
    usuario = usuario_service.crear(
        db,
        usuario_service.DatosUsuarioNuevo(
            username="uow_prueba", nombre="UoW", correo="uow@example.com",
            rol=RolUsuario.encargado, password="Riego2026segura",
        ),
        actor=None, contexto=SISTEMA,
    )
    assert usuario.id is not None  # flush asignó el id
    assert llamadas == []
