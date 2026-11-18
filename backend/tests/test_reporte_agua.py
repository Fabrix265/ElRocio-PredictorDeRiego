"""Reporte de agua: riego real (solo aplicado), modelo y modelo modificado (edición/corrección)."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest
import time_machine
from sqlalchemy import select

from app.models import (Cronograma, CronogramaCiclo, CronogramaTurno, CronogramaVersion, MotivoCorreccion)
from app.models.enums import EstadoRiego, OrigenRiego, OrigenVersion, RolUsuario
from app.repositories import riego as repo_riego
from app.services import reportes_service
from app.services.riego_service import _crear_registro

FECHA = dt.date(2026, 11, 9)


@pytest.fixture(autouse=True)
def reloj():
    with time_machine.travel(dt.datetime(2026, 11, 11, 15, tzinfo=dt.UTC), tick=False):
        yield


def _version(db, crono, numero, origen, m3ha_por_turno, **extra):
    v = CronogramaVersion(cronograma_id=crono.id, numero=numero, origen=origen, **extra)
    db.add(v)
    db.flush()
    for t in repo_riego.turnos_de_modulo(db, 1):
        m3ha = m3ha_por_turno.get(t.codigo, 20)
        db.add(CronogramaTurno(version_id=v.id, turno_id=t.id, n_ciclos=1, n_ciclos_modelo=1, area_ha=t.area_ha,
                               factor_min_por_m3ha=2))
        db.add(CronogramaCiclo(version_id=v.id, turno_id=t.id, ciclo=1, riego_m3ha=m3ha, riego_m3=m3ha * t.area_ha,
                               duracion_min=2 * m3ha, inicio_min=360, fin_min=360 + 2 * m3ha,
                               hora_inicio="06:00", hora_fin="06:40"))
    db.flush()
    return v


def _riego(db, codigo, estado, origen, m3ha):
    turno = next(t for t in repo_riego.turnos_de_modulo(db, 1) if t.codigo == codigo)
    ciclo = {"inicio_min": 360.0, "fin_min": 400.0, "duracion_min": 40.0, "riego_m3ha": m3ha,
             "riego_m3": round(m3ha * turno.area_ha, 1), "area_ha": turno.area_ha, "valvula": None,
             "hora_inicio": "06:00", "hora_fin": "06:40", "fin_dia_siguiente": False}
    _crear_registro(db, turno=turno, fecha=FECHA, vigente=None, ciclos=[ciclo], estado=estado, origen=origen,
                    actor=None)


@pytest.fixture
def escenario(db):
    motivo = db.scalars(select(MotivoCorreccion).order_by(MotivoCorreccion.orden)).first()
    c = Cronograma(modulo_id=1, fecha=FECHA)
    db.add(c)
    db.flush()
    modelo = _version(db, c, 1, OrigenVersion.modelo, {})
    editada = _version(db, c, 2, OrigenVersion.correccion, {"TE01": 25}, basada_en_id=modelo.id,
                       motivo_codigo=motivo.codigo, motivo_comentario="lluvia")
    c.version_publicada_id = editada.id
    _riego(db, "TE01", EstadoRiego.provisional, OrigenRiego.cronograma, 25)
    _riego(db, "TE02", EstadoRiego.aplicado, OrigenRiego.controlador, 18.5)
    db.commit()
    return motivo


def test_agua_separa_real_modelo_y_modificado(db, escenario):
    encargado = SimpleNamespace(rol=RolUsuario.encargado)
    dia = reportes_service.agua(db, 1, FECHA, FECHA, encargado)["dias"][0]
    assert dia["modificado"] is True and dia["propuesta_version"] == 2 and dia["modelo_version"] == 1
    assert dia["propuesta_origen"] == "correccion" and dia["propuesta_publicada"] is True
    assert dia["motivo"] == f"{escenario.nombre} · lluvia"
    turnos = {t["turno_codigo"]: t for t in dia["turnos"]}
    te01, te02 = turnos["TE01"], turnos["TE02"]
    assert te01["modificado"] is True and te02["modificado"] is False
    assert (te01["modelo_m3ha"], te01["propuesto_m3ha"]) == (20, 25)
    # El provisional no es riego real; el del controlador sí.
    assert te01["estado_riego"] == "provisional" and te01["real_m3ha"] is None and te01["aplicado_m3ha"] == 25
    assert te02["real_m3ha"] == 18.5 and te02["origen_riego"] == "controlador"


def test_el_modelo_es_la_ultima_version_generada_por_el_modelo(db):
    # v1 modelo (20) -> v2 corrección (TE01 25) -> v3 regenerada (30) -> v4 corrige la v3 (TE01 28).
    # «Modelo» = lo último que dio el modelo (v3) y «Modificado» = lo publicado (v4).
    motivo = db.scalars(select(MotivoCorreccion).order_by(MotivoCorreccion.orden)).first()
    c = Cronograma(modulo_id=1, fecha=FECHA)
    db.add(c)
    db.flush()
    todos = {t.codigo: 30 for t in repo_riego.turnos_de_modulo(db, 1)}
    v1 = _version(db, c, 1, OrigenVersion.modelo, {})
    v2 = _version(db, c, 2, OrigenVersion.correccion, {"TE01": 25}, basada_en_id=v1.id, motivo_codigo=motivo.codigo)
    v3 = _version(db, c, 3, OrigenVersion.regenerado, todos, basada_en_id=v2.id)
    v4 = _version(db, c, 4, OrigenVersion.correccion, todos | {"TE01": 28}, basada_en_id=v3.id,
                  motivo_codigo=motivo.codigo)
    c.version_publicada_id = v4.id
    db.commit()
    dia = reportes_service.agua(db, 1, FECHA, FECHA, SimpleNamespace(rol=RolUsuario.encargado))["dias"][0]
    assert (dia["modelo_version"], dia["propuesta_version"]) == (3, 4)
    turnos = {t["turno_codigo"]: t for t in dia["turnos"]}
    assert (turnos["TE01"]["modelo_m3ha"], turnos["TE01"]["propuesto_m3ha"]) == (30, 28)


def test_el_programador_no_ve_el_modelo_pero_si_que_hubo_cambios(db, escenario):
    programador = SimpleNamespace(rol=RolUsuario.programador)
    dia = reportes_service.agua(db, 1, FECHA, FECHA, programador)["dias"][0]
    assert dia["modelo_version"] is None and dia["modificado"] is True
    assert all(t["modelo_m3ha"] is None for t in dia["turnos"])
