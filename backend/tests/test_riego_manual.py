"""Edición manual del riego: eliminar un registro equivocado y marcar aplicado el riego de hoy."""
from __future__ import annotations

import datetime as dt

import pytest
import time_machine
from sqlalchemy import select

from app.models import Auditoria, RiegoRegistro, Turno
from tests.conftest import API

HOY = dt.date(2026, 11, 11)
AYER = HOY - dt.timedelta(days=1)


@pytest.fixture(autouse=True)
def reloj():
    # 15:00 UTC = 10:00 en Lima.
    with time_machine.travel(dt.datetime(2026, 11, 11, 15, tzinfo=dt.UTC), tick=False):
        yield


@pytest.fixture
def turno_id(db) -> int:
    return db.scalars(select(Turno.id).order_by(Turno.id)).first()


def guardar(client, cabeceras, turno_id, fecha, *, estado="provisional", basado_en_id=None,
            ciclos=None, sin_riego=False):
    ciclos = [] if sin_riego else (ciclos or [{"inicio_min": 360, "duracion_min": 60, "riego_m3ha": 20}])
    return client.post(f"{API}/riego/registros", headers=cabeceras, json={
        "turno_id": turno_id, "fecha": str(fecha), "basado_en_id": basado_en_id, "estado": estado,
        "sin_riego": sin_riego, "motivo": "Prueba", "ciclos": ciclos,
    })


def eliminar(client, cabeceras, registro_id, motivo="  Lo cargué en el turno equivocado  "):
    return client.request("DELETE", f"{API}/riego/registros/{registro_id}", headers=cabeceras,
                          json={"motivo": motivo})


def test_eliminar_deja_el_turno_dia_sin_registro_y_conserva_el_historial(client, auth, db, turno_id):
    cabeceras = auth("encargado")
    v1 = guardar(client, cabeceras, turno_id, AYER).json()
    v2 = guardar(client, cabeceras, turno_id, AYER, estado="aplicado", basado_en_id=v1["id"]).json()

    r = eliminar(client, cabeceras, v2["id"])
    assert r.status_code == 200, r.text
    assert r.json() == {"turno_id": turno_id, "fecha": str(AYER), "version": 2}

    listado = client.get(f"{API}/riego", headers=cabeceras, params={"modulo_id": 1, "desde": str(AYER),
                                                                     "hasta": str(AYER)}).json()
    assert [x for x in listado["registros"] if x["turno_id"] == turno_id] == []
    versiones = client.get(f"{API}/riego/{turno_id}/{AYER}/versiones", headers=cabeceras).json()
    assert [(v["version"], v["vigente"]) for v in versiones] == [(1, False), (2, False)]
    evento = db.scalars(select(Auditoria).where(Auditoria.accion == "riego_eliminado")).one()
    assert evento.entidad_id == str(v2["id"])
    assert evento.detalle["motivo"] == "Lo cargué en el turno equivocado"
    assert evento.detalle["estado"] == "aplicado"

    # Se puede volver a registrar después: sigue la numeración de versiones.
    v3 = guardar(client, cabeceras, turno_id, AYER)
    assert v3.status_code == 201, v3.text
    assert v3.json()["version"] == 3


def test_eliminar_una_version_que_ya_no_es_la_vigente_es_conflicto(client, auth, turno_id):
    cabeceras = auth("admin")
    v1 = guardar(client, cabeceras, turno_id, AYER).json()
    guardar(client, cabeceras, turno_id, AYER, sin_riego=True, basado_en_id=v1["id"])
    assert eliminar(client, cabeceras, v1["id"]).status_code == 409
    assert eliminar(client, cabeceras, 999999).status_code == 404


def test_eliminar_exige_motivo_y_rol_editor(client, auth, db, turno_id):
    subgerente = auth("subgerente")
    v1 = guardar(client, subgerente, turno_id, AYER).json()
    assert eliminar(client, auth("programador"), v1["id"]).status_code == 403
    assert eliminar(client, auth("encargado"), v1["id"], motivo="   ").status_code == 422
    assert db.get(RiegoRegistro, v1["id"]).vigente
    assert eliminar(client, subgerente, v1["id"]).status_code == 200


def test_hoy_se_marca_aplicado_solo_cuando_termino_el_ultimo_ciclo(client, auth, turno_id):
    cabeceras = auth("encargado")
    temprano = [{"inicio_min": 360, "duracion_min": 60, "riego_m3ha": 20}]  # 06:00–07:00
    tarde = [*temprano, {"inicio_min": 600, "duracion_min": 30, "riego_m3ha": 10}]  # 10:00–10:30

    r = guardar(client, cabeceras, turno_id, HOY, estado="aplicado", ciclos=tarde)
    assert r.status_code == 422
    assert "10:30" in r.json()["detail"]

    r = guardar(client, cabeceras, turno_id, HOY, estado="aplicado", ciclos=temprano)
    assert r.status_code == 201, r.text
    assert r.json()["estado"] == "aplicado"


def test_un_dia_futuro_nunca_se_marca_aplicado(client, auth, turno_id):
    r = guardar(client, auth("admin"), turno_id, HOY + dt.timedelta(days=1), estado="aplicado")
    assert r.status_code == 422
    assert "futuro" in r.json()["detail"]


def test_un_ciclo_que_termina_pasada_la_medianoche_espera_al_dia_siguiente(client, auth, turno_id):
    nocturno = [{"inicio_min": 1380, "duracion_min": 120, "riego_m3ha": 20}]  # 23:00–01:00
    r = guardar(client, auth("admin"), turno_id, HOY, estado="aplicado", ciclos=nocturno)
    assert r.status_code == 422
    assert "01:00 del día siguiente" in r.json()["detail"]
