"""Consulta de auditoría (admin y subgerente), lista blanca del detalle y catálogos."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tiempo import ahora_utc, hoy_lima
from app.models import Usuario
from app.services import auditoria_service
from tests.conftest import API, login


@pytest.mark.parametrize("rol", ["encargado", "programador"])
def test_auditoria_403_para_encargado_y_programador(client: TestClient, auth, rol: str):
    cabeceras = auth(rol)
    assert client.get(f"{API}/auditoria", headers=cabeceras).status_code == 403
    assert client.get(f"{API}/auditoria/opciones", headers=cabeceras).status_code == 403


@pytest.mark.parametrize("rol", ["admin", "subgerente"])
def test_auditoria_visible_para_admin_y_subgerente(client: TestClient, auth, rol: str):
    cabeceras = auth(rol)
    respuesta = client.get(f"{API}/auditoria", headers=cabeceras)
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["page"] == 1 and cuerpo["page_size"] == 50 and cuerpo["total"] >= 1
    item = cuerpo["items"][0]
    assert set(item) == {"id", "ocurrido_at", "usuario_id", "username", "rol", "accion", "entidad",
                         "entidad_id", "detalle", "ip", "user_agent"}
    assert item["accion"] == "login"
    assert item["ocurrido_at"][-6] in "+-"  # ISO 8601 con zona


def test_auditoria_filtra_y_pagina(client: TestClient, auth, crear_usuario, db: Session):
    cabeceras = auth("admin", username="jefa")
    crear_usuario("uli")
    login(client, "uli", "mala-clave-1")
    login(client, "uli")
    login(client, "uli")
    uli = db.scalars(select(Usuario).where(Usuario.username == "uli")).one()

    def consultar(**params):
        respuesta = client.get(f"{API}/auditoria", headers=cabeceras, params=params)
        assert respuesta.status_code == 200, respuesta.text
        return respuesta.json()

    assert consultar(accion="login_fallido")["total"] == 1
    por_usuario = consultar(usuario_id=uli.id)
    # El login fallido de un usuario existente queda a su nombre (aparece en su filtro).
    assert por_usuario["total"] == 3
    assert sorted(i["accion"] for i in por_usuario["items"]) == ["login", "login", "login_fallido"]
    assert consultar(entidad="usuario", entidad_id=str(uli.id))["total"] == 3

    pagina = consultar(page=2, page_size=2)
    assert pagina["total"] == 4 and len(pagina["items"]) == 2 and pagina["page"] == 2
    primera = consultar(page=1, page_size=2)["items"]
    assert primera[0]["ocurrido_at"] >= primera[1]["ocurrido_at"]  # más reciente primero

    hoy = hoy_lima().isoformat()
    assert consultar(desde=hoy, hasta=hoy)["total"] == 4
    manana = (hoy_lima() + timedelta(days=1)).isoformat()
    assert consultar(desde=manana)["total"] == 0
    malo = client.get(f"{API}/auditoria", headers=cabeceras, params={"desde": "07/11/2026"})
    assert malo.status_code == 422
    assert malo.json()["detail"].startswith("El parámetro desde no es una fecha válida")
    assert client.get(f"{API}/auditoria", headers=cabeceras, params={"page_size": 500}).status_code == 422


def test_auditoria_opciones(client: TestClient, auth):
    cabeceras = auth("subgerente", username="sub")
    opciones = client.get(f"{API}/auditoria/opciones", headers=cabeceras).json()
    assert "login" in opciones["acciones"] and "usuario_creado" in opciones["acciones"]
    assert opciones["entidades"] == ["usuario"]
    assert {"id", "username", "nombre"} <= set(opciones["usuarios"][0])
    assert "sub" in [u["username"] for u in opciones["usuarios"]]


def test_detalle_nunca_guarda_secretos(db: Session):
    fila = auditoria_service.registrar(
        db,
        accion="prueba",
        entidad="usuario",
        detalle={
            "antes": {"nombre": "A", "password_hash": "$argon2id$..."},
            "despues": {"nombre": "B", "token": "abc", "anidado": [{"api_key": "x", "ok": 1}]},
        },
    )
    db.commit()
    texto = json.dumps(fila.detalle)
    assert fila.detalle == {"antes": {"nombre": "A"}, "despues": {"nombre": "B", "anidado": [{"ok": 1}]}}
    assert "argon2" not in texto and "abc" not in texto


def test_auditoria_usa_el_reloj_de_la_app(db: Session):
    with time_machine.travel(ahora_utc() - timedelta(days=3), tick=False):
        fila = auditoria_service.registrar(db, accion="prueba", entidad="usuario")
        db.commit()
    assert ahora_utc() - fila.ocurrido_at > timedelta(days=2)


# --- Catálogos ----------------------------------------------------------------

def test_fundos_con_modulos_y_turnos(client: TestClient, auth):
    assert client.get(f"{API}/fundos").status_code == 401
    cabeceras = auth("programador")
    fundos = client.get(f"{API}/fundos", headers=cabeceras).json()
    assert len(fundos) == 1
    fundo = fundos[0]
    assert fundo["codigo"] == "EN01" and fundo["nombre"] == "ENSUEÑO 1"
    modulo = fundo["modulos"][0]
    assert modulo["codigo"] == "EN01-MOD5" and modulo["area_ha"] == pytest.approx(62.8292)
    assert [t["codigo"] for t in modulo["turnos"]] == ["TE01", "TE02", "TE03", "TE04", "TE05"]
    assert modulo["turnos"][0] == {
        "id": modulo["turnos"][0]["id"], "codigo": "TE01", "orden": 1, "area_ha": 13.019,
        "valvula_controlador": "6061000",
    }


def test_motivos_de_correccion(client: TestClient, auth):
    cabeceras = auth("encargado")
    motivos = client.get(f"{API}/motivos-correccion", headers=cabeceras).json()
    assert [m["codigo"] for m in motivos] == [
        "clima_lluvia", "criterio_agronomico", "programa_semanal", "falla_equipo",
        "operacion_personal", "otro",
    ]
    assert motivos[1]["nombre"] == "Criterio agronómico"


ENORME = "99999999999999999999"  # más que un bigint


@pytest.mark.parametrize(
    ("metodo", "ruta", "params", "cuerpo"),
    [
        ("get", "/auditoria", {"page": ENORME}, None),
        ("get", "/auditoria", {"page": "100001"}, None),
        ("get", "/auditoria", {"usuario_id": ENORME}, None),
        ("get", "/auditoria", {"usuario_id": "0"}, None),
        ("get", f"/usuarios/{ENORME}", None, None),
        ("get", "/usuarios/0", None, None),
        ("patch", f"/usuarios/{ENORME}", None, {"nombre": "X"}),
        ("post", f"/usuarios/{ENORME}/password-temporal", None, {"password_temporal": "Temporal2026x"}),
    ],
)
def test_ids_y_paginas_fuera_de_rango_dan_422(client: TestClient, auth, metodo, ruta, params, cuerpo):
    cabeceras = auth("admin", username="jefa_rangos")
    kwargs = {"headers": cabeceras, "params": params}
    if cuerpo is not None:
        kwargs["json"] = cuerpo
    respuesta = getattr(client, metodo)(f"{API}{ruta}", **kwargs)
    assert respuesta.status_code == 422, respuesta.text
    assert "Traceback" not in respuesta.text
    assert isinstance(respuesta.json()["detail"], list)
