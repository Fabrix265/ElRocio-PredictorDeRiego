"""Gestión de usuarios (solo admin), reglas de último admin y revocación inmediata."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Auditoria, Usuario
from tests.conftest import API, bearer, login, token_de

NUEVO = {
    "username": "Nuevo.Usuario",
    "nombre": "Nuevo Usuario",
    "correo": "Nuevo@Example.com",
    "rol": "programador",
    "password_temporal": "Temporal2026",
}


@pytest.mark.parametrize("rol", ["encargado", "programador", "subgerente"])
def test_usuarios_403_para_roles_no_admin(client: TestClient, auth, rol: str):
    cabeceras = auth(rol)
    for metodo, ruta, cuerpo in (
        ("GET", "/usuarios", None),
        ("POST", "/usuarios", NUEVO),
        ("GET", "/usuarios/1", None),
        ("PATCH", "/usuarios/1", {"nombre": "X"}),
        ("POST", "/usuarios/1/password-temporal", {"password_temporal": "Temporal2026"}),
    ):
        respuesta = client.request(metodo, f"{API}{ruta}", headers=cabeceras, json=cuerpo)
        assert respuesta.status_code == 403, (metodo, ruta)
        assert respuesta.json() == {"detail": "No tienes permiso para realizar esta acción"}


def test_usuarios_sin_sesion_401(client: TestClient):
    assert client.get(f"{API}/usuarios").status_code == 401


def test_alta_listado_y_detalle(client: TestClient, auth, db: Session):
    cabeceras = auth("admin", username="jefa")
    respuesta = client.post(f"{API}/usuarios", headers=cabeceras, json=NUEVO)
    assert respuesta.status_code == 201, respuesta.text
    creado = respuesta.json()
    assert creado["username"] == "nuevo.usuario"
    assert creado["correo"] == "nuevo@example.com"
    assert creado["debe_cambiar_password"] is True and creado["activo"] is True
    assert "password_hash" not in creado

    usuario = db.get(Usuario, creado["id"])
    assert usuario.password_hash.startswith("$argon2id$")
    assert usuario.creado_por == db.scalars(select(Usuario.id).where(Usuario.username == "jefa")).one()

    # El nuevo usuario entra con la temporal y debe cambiarla.
    primer = login(client, "nuevo.usuario", "Temporal2026")
    assert primer.json()["usuario"]["debe_cambiar_password"] is True

    lista = client.get(f"{API}/usuarios", headers=cabeceras).json()
    assert [u["username"] for u in lista] == ["jefa", "nuevo.usuario"]
    assert [u["username"] for u in client.get(f"{API}/usuarios", headers=cabeceras,
                                               params={"rol": "programador"}).json()] == ["nuevo.usuario"]
    assert [u["username"] for u in client.get(f"{API}/usuarios", headers=cabeceras,
                                               params={"q": "NUEVO"}).json()] == ["nuevo.usuario"]
    assert client.get(f"{API}/usuarios", headers=cabeceras, params={"activo": "false"}).json() == []
    assert client.get(f"{API}/usuarios", headers=cabeceras, params={"q": "%"}).json() == []

    detalle = client.get(f"{API}/usuarios/{creado['id']}", headers=cabeceras)
    assert detalle.status_code == 200 and detalle.json()["nombre"] == "Nuevo Usuario"
    no_existe = client.get(f"{API}/usuarios/999999", headers=cabeceras)
    assert no_existe.status_code == 404
    assert no_existe.json() == {"detail": "Usuario no encontrado"}

    fila = db.scalars(select(Auditoria).where(Auditoria.accion == "usuario_creado")).one()
    assert fila.username == "jefa" and fila.rol == "admin" and fila.entidad_id == str(creado["id"])
    assert fila.detalle["despues"]["username"] == "nuevo.usuario"
    assert "hash" not in json.dumps(fila.detalle) and "Temporal2026" not in json.dumps(fila.detalle)


def test_alta_valida_datos(client: TestClient, auth):
    cabeceras = auth("admin", username="jefa")
    assert client.post(f"{API}/usuarios", headers=cabeceras, json=NUEVO).status_code == 201

    duplicado = client.post(f"{API}/usuarios", headers=cabeceras,
                            json={**NUEVO, "username": "NUEVO.usuario", "correo": "otro@example.com"})
    assert duplicado.status_code == 409
    assert duplicado.json() == {"detail": "Ya existe un usuario con ese nombre de usuario."}
    correo_dup = client.post(f"{API}/usuarios", headers=cabeceras, json={**NUEVO, "username": "otro"})
    assert correo_dup.status_code == 409
    assert correo_dup.json() == {"detail": "Ya existe un usuario con ese correo."}

    debil = client.post(f"{API}/usuarios", headers=cabeceras,
                        json={**NUEVO, "username": "otro2", "correo": "o2@example.com",
                              "password_temporal": "sololetras"})
    assert debil.status_code == 422
    assert debil.json() == {"detail": "La contraseña debe incluir letras y números."}

    invalido = client.post(f"{API}/usuarios", headers=cabeceras,
                           json={**NUEVO, "username": "con espacio", "correo": "no-es-correo",
                                 "rol": "jefe"})
    assert invalido.status_code == 422
    campos = {tuple(e["loc"]): e["msg"] for e in invalido.json()["detail"]}
    assert campos[("body", "username")].startswith("El usuario debe tener de 3 a 60 caracteres")
    assert campos[("body", "correo")] == "Ingresa un correo válido."
    assert campos[("body", "rol")].startswith("Valor no válido.")


def test_edicion_y_auditoria_antes_despues(client: TestClient, auth, crear_usuario, db: Session):
    cabeceras = auth("admin", username="jefa")
    otro = crear_usuario("pepe", rol="encargado")
    respuesta = client.patch(f"{API}/usuarios/{otro.id}", headers=cabeceras,
                             json={"nombre": "José Pérez", "correo": "JOSE@example.com"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["nombre"] == "José Pérez"
    assert respuesta.json()["correo"] == "jose@example.com"

    fila = db.scalars(select(Auditoria).where(Auditoria.accion == "usuario_editado")).one()
    assert fila.detalle == {
        "antes": {"nombre": "Usuario pepe", "correo": "pepe@example.com"},
        "despues": {"nombre": "José Pérez", "correo": "jose@example.com"},
    }
    # Editar nombre/correo no corta la sesión del usuario.
    assert db.get(Usuario, otro.id).token_version == 0

    vacio = client.patch(f"{API}/usuarios/{otro.id}", headers=cabeceras, json={})
    assert vacio.status_code == 200


def test_no_puede_desactivarse_a_si_mismo(client: TestClient, auth, crear_usuario, db: Session):
    cabeceras = auth("admin", username="jefa")
    crear_usuario("otra_admin", rol="admin")
    yo = db.scalars(select(Usuario).where(Usuario.username == "jefa")).one()
    respuesta = client.patch(f"{API}/usuarios/{yo.id}", headers=cabeceras, json={"activo": False})
    assert respuesta.status_code == 400
    assert respuesta.json() == {"detail": "No puedes desactivar tu propio usuario."}


def test_no_deja_el_sistema_sin_admin(client: TestClient, auth, db: Session):
    cabeceras = auth("admin", username="unica")
    yo = db.scalars(select(Usuario).where(Usuario.username == "unica")).one()
    respuesta = client.patch(f"{API}/usuarios/{yo.id}", headers=cabeceras, json={"rol": "encargado"})
    assert respuesta.status_code == 400
    assert respuesta.json() == {"detail": "Debe quedar al menos un administrador activo."}
    db.refresh(yo)
    assert yo.rol.value == "admin"


def test_desactivar_revoca_acceso_inmediato(client: TestClient, auth, crear_usuario, db: Session):
    cabeceras = auth("admin", username="jefa")
    victima = crear_usuario("rafa", rol="admin")
    token_victima = token_de(client, "rafa")
    rt_victima = client.cookies["rt"]
    assert client.get(f"{API}/usuarios", headers=bearer(token_victima)).status_code == 200

    respuesta = client.patch(f"{API}/usuarios/{victima.id}", headers=cabeceras, json={"activo": False})
    assert respuesta.status_code == 200 and respuesta.json()["activo"] is False

    # El access token anterior deja de servir al instante (401), y el refresh también.
    assert client.get(f"{API}/usuarios", headers=bearer(token_victima)).status_code == 401
    client.cookies.clear()
    refresh = client.post(f"{API}/auth/refresh",
                          headers={"X-Requested-With": "fetch", "Cookie": f"rt={rt_victima}"})
    assert refresh.status_code == 401
    assert login(client, "rafa").status_code == 401

    fila = db.scalars(select(Auditoria).where(Auditoria.accion == "usuario_desactivado")).one()
    assert fila.detalle == {"antes": {"activo": True}, "despues": {"activo": False}}

    # Reactivar: vuelve a entrar.
    activar = client.patch(f"{API}/usuarios/{victima.id}", headers=cabeceras, json={"activo": True})
    assert activar.status_code == 200
    assert login(client, "rafa").status_code == 200
    assert "usuario_activado" in set(db.scalars(select(Auditoria.accion)))


def test_cambiar_rol_revoca_sesiones(client: TestClient, auth, crear_usuario, db: Session):
    cabeceras = auth("admin", username="jefa")
    otro = crear_usuario("susi", rol="encargado")
    token_otro = token_de(client, "susi")
    respuesta = client.patch(f"{API}/usuarios/{otro.id}", headers=cabeceras, json={"rol": "subgerente"})
    assert respuesta.status_code == 200 and respuesta.json()["rol"] == "subgerente"
    assert client.get(f"{API}/auth/me", headers=bearer(token_otro)).status_code == 401
    fila = db.scalars(select(Auditoria).where(Auditoria.accion == "rol_cambiado")).one()
    assert fila.detalle == {"antes": {"rol": "encargado"}, "despues": {"rol": "subgerente"}}


def test_password_temporal(client: TestClient, auth, crear_usuario, db: Session):
    cabeceras = auth("admin", username="jefa")
    otro = crear_usuario("tere", rol="programador")
    token_otro = token_de(client, "tere")
    debil = client.post(f"{API}/usuarios/{otro.id}/password-temporal", headers=cabeceras,
                        json={"password_temporal": "123"})
    assert debil.status_code == 422
    respuesta = client.post(f"{API}/usuarios/{otro.id}/password-temporal", headers=cabeceras,
                            json={"password_temporal": "NuevaTemp2026"})
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json()["debe_cambiar_password"] is True
    assert client.get(f"{API}/auth/me", headers=bearer(token_otro)).status_code == 401
    assert login(client, "tere", "NuevaTemp2026").json()["usuario"]["debe_cambiar_password"] is True
    fila = db.scalars(select(Auditoria).where(Auditoria.accion == "password_temporal_asignado")).one()
    assert "NuevaTemp2026" not in json.dumps(fila.detalle) and "hash" not in json.dumps(fila.detalle)
