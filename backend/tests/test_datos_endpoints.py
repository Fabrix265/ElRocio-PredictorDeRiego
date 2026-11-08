"""Endpoints de datos de campo, frescura, ingestas y turnos: permisos por rol, frescura (§3.3),
series, "Actualizar ahora" (202 + segundo plano) y listado de corridas sin secretos."""

from __future__ import annotations

import datetime as dt

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    AmbienteDiario,
    IngestaCorrida,
    MeteoLectura,
    PhytechPlantaDiario,
    PronosticoClima,
    RiegoCiclo,
    RiegoRegistro,
    Turno,
)
from app.models.enums import DisparoIngesta, EstadoIngesta, EstadoRiego, OrigenMeteo, OrigenRiego
from app.repositories import datos_campo as repo_datos
from app.services import ingesta_service
from tests.conftest import API

HOY = dt.date(2026, 11, 8)
TODOS = ("admin", "encargado", "subgerente", "programador")


@pytest.fixture(autouse=True)
def reloj():
    with time_machine.travel("2026-11-08 10:00 -05:00", tick=False):
        yield


@pytest.fixture
def modulo(db):
    return repo_datos.modulo_por_codigo(db, "EN01-MOD5")


@pytest.fixture
def turnos(db, modulo):
    return list(db.scalars(select(Turno).where(Turno.modulo_id == modulo.id).order_by(Turno.orden)))


def _dia(n: int) -> dt.date:
    return dt.date(2026, 11, n)


def _registro(db, modulo, turno, fecha, estado=EstadoRiego.aplicado, m3=300.0, minutos=90.0):
    registro = RiegoRegistro(modulo_id=modulo.id, turno_id=turno.id, fecha=fecha, version=1, vigente=True,
                             estado=estado, origen=OrigenRiego.historico, contenido_sha256="0" * 64)
    registro.ciclos = [RiegoCiclo(inicio_min=360, fin_min=360 + minutos, duracion_min=minutos, riego_m3=m3,
                                  riego_m3ha=m3 / turno.area_ha, area_ha=turno.area_ha, hora_inicio="06:00",
                                  hora_fin="07:30")]
    db.add(registro)


# --- Permisos -------------------------------------------------------------------

RUTAS_TODOS = ("/datos/frescura?modulo_id={m}", "/datos/clima", "/datos/clima?resolucion=30min",
               "/datos/suelo", "/datos/suelo?resolucion=horaria", "/datos/planta", "/datos/pronostico",
               "/modulos/{m}/turnos")


@pytest.mark.parametrize("rol", TODOS)
def test_datos_y_turnos_para_todos_los_roles(client: TestClient, auth, modulo, rol):
    cabeceras = auth(rol)
    for ruta in RUTAS_TODOS:
        respuesta = client.get(API + ruta.format(m=modulo.id), headers=cabeceras)
        assert respuesta.status_code == 200, (ruta, respuesta.text)


def test_sin_sesion_401(client: TestClient, modulo):
    for ruta in (*RUTAS_TODOS, "/ingestas"):
        assert client.get(API + ruta.format(m=modulo.id)).status_code == 401
    assert client.post(f"{API}/ingestas/ejecutar", json={}).status_code == 401


@pytest.mark.parametrize("rol,codigo", [("admin", 200), ("encargado", 200), ("subgerente", 200), ("programador", 403)])
def test_listar_ingestas_por_rol(client: TestClient, auth, rol, codigo):
    assert client.get(f"{API}/ingestas", headers=auth(rol)).status_code == codigo


@pytest.mark.parametrize("rol,codigo", [("admin", 202), ("encargado", 202), ("subgerente", 403), ("programador", 403)])
def test_actualizar_ahora_por_rol(client: TestClient, auth, monkeypatch, rol, codigo):
    monkeypatch.setattr(ingesta_service, "ejecutar_en_segundo_plano", lambda ids: None)
    respuesta = client.post(f"{API}/ingestas/ejecutar", json={"fuentes": ["pronostico"]}, headers=auth(rol))
    assert respuesta.status_code == codigo, respuesta.text


# --- Ingestas -------------------------------------------------------------------

def test_actualizar_ahora_crea_corridas_y_las_lanza_en_segundo_plano(client: TestClient, auth, db, monkeypatch):
    lanzadas: list[list[int]] = []
    monkeypatch.setattr(ingesta_service, "ejecutar_en_segundo_plano", lambda ids: lanzadas.append(list(ids)))
    cabeceras = auth("encargado", username="eli")
    respuesta = client.post(f"{API}/ingestas/ejecutar", json={}, headers=cabeceras)
    assert respuesta.status_code == 202
    corridas = respuesta.json()
    assert [c["fuente"] for c in corridas] == list(ingesta_service.FUENTES)
    assert {(c["estado"], c["disparo"], c["usuario"]) for c in corridas} == {("en_curso", "manual", "eli")}
    assert lanzadas == [[c["id"] for c in corridas]]
    # Quedó confirmado antes de responder (lo ve la tarea de fondo) y no se lanza dos veces.
    assert db.get(IngestaCorrida, corridas[0]["id"]).estado == EstadoIngesta.en_curso
    otra = client.post(f"{API}/ingestas/ejecutar", json={"fuentes": ["weatherlink"]}, headers=cabeceras)
    assert otra.status_code == 409 and "weatherlink" in otra.json()["detail"]


@pytest.mark.parametrize("cuerpo", [
    {"fuentes": ["clima_marciano"]},
    {"desde": "2026-11-01", "hasta": "2026-11-08"},  # hasta = hoy
    {"desde": "2026-11-07", "hasta": "2026-11-01"},
    {"desde": "2026-01-01", "hasta": "2026-11-07"},  # más de 62 días
    {"fuentes": ["weatherlink"], "api_key": "x"},
    {"desde": "0001-01-01", "hasta": "0001-01-02"},  # antes de los datos: llamadas absurdas
    {"desde": "2016-12-31", "hasta": "2017-01-01"},
])
def test_actualizar_ahora_valida_la_peticion(client: TestClient, auth, monkeypatch, cuerpo):
    monkeypatch.setattr(ingesta_service, "ejecutar_en_segundo_plano", lambda ids: None)
    respuesta = client.post(f"{API}/ingestas/ejecutar", json=cuerpo, headers=auth("admin"))
    assert respuesta.status_code == 422, respuesta.text


def test_listar_ingestas_sin_secretos_y_mas_recientes_primero(client: TestClient, auth, db):
    vieja = IngestaCorrida(fuente="phytech_suelo", disparo=DisparoIngesta.programado, fecha_programada=_dia(7),
                           inicio_at=dt.datetime(2026, 11, 7, 10, tzinfo=dt.UTC), estado=EstadoIngesta.error,
                           errores=[{"tipo": "credenciales", "status_code": 401, "endpoint": "/auth/api-token",
                                     "mensaje": "Phytech rechazó las credenciales"}])
    nueva = IngestaCorrida(fuente="weatherlink", disparo=DisparoIngesta.script,
                           inicio_at=dt.datetime(2026, 11, 8, 10, tzinfo=dt.UTC), estado=EstadoIngesta.ok,
                           desde=_dia(5), hasta=_dia(7), filas_nuevas=144)
    db.add_all([vieja, nueva])
    db.commit()
    respuesta = client.get(f"{API}/ingestas", headers=auth("subgerente"))
    cuerpo = respuesta.json()
    assert [c["fuente"] for c in cuerpo[:2]] == ["weatherlink", "phytech_suelo"]
    assert cuerpo[1]["errores"] == [{"tipo": "credenciales", "status_code": 401, "endpoint": "/auth/api-token",
                                     "mensaje": "Phytech rechazó las credenciales"}]
    assert set(cuerpo[0]) == {"id", "fuente", "disparo", "usuario", "fecha_programada", "desde", "hasta",
                              "inicio_at", "fin_at", "duracion_ms", "estado", "filas_nuevas",
                              "filas_actualizadas", "filas_omitidas", "conflictos", "errores"}
    solo = client.get(f"{API}/ingestas", params={"fuente": "weatherlink", "limite": 1}, headers=auth("admin"))
    assert [c["id"] for c in solo.json()] == [nueva.id]
    assert client.get(f"{API}/ingestas", params={"limite": 0}, headers=auth("admin", username="a2")).status_code == 422


# --- Frescura -------------------------------------------------------------------

def _fuente(cuerpo, nombre):
    return next(f for f in cuerpo["fuentes"] if f["fuente"] == nombre)


def test_frescura_por_fuente_con_huecos(client: TestClient, auth, db, modulo, turnos):
    fundo_id = modulo.fundo_id
    for n in range(1, 8):
        for turno in turnos:
            if n == 7:
                _registro(db, modulo, turno, _dia(n), EstadoRiego.provisional)
            elif not (turno.codigo == "TE03" and n == 4):
                _registro(db, modulo, turno, _dia(n))
        db.add(AmbienteDiario(fundo_id=fundo_id, fecha=_dia(n), tiene_meteo=0 if n == 3 else 1,
                              tiene_suelo=1, tiene_planta=1,
                              hum_zona_radicular_cierre=30.0 if n <= 5 else None))
    db.commit()

    respuesta = client.get(f"{API}/datos/frescura", params={"modulo_id": modulo.id, "dias": 7},
                           headers=auth("programador"))
    assert respuesta.status_code == 200
    cuerpo = respuesta.json()
    assert cuerpo["fecha"] == "2026-11-08" and cuerpo["referencia"] == "2026-11-07"
    assert [f["fuente"] for f in cuerpo["fuentes"]] == [
        "riego_aplicado", "riego_provisional", "weatherlink", "phytech_suelo", "phytech_planta", "ndvi", "pronostico"]

    aplicado = _fuente(cuerpo, "riego_aplicado")
    assert (aplicado["estado"], aplicado["ultima_fecha"], aplicado["huecos"]) == ("naranja", "2026-11-06", ["2026-11-04"])
    te03 = next(t for t in aplicado["por_turno"] if t["turno_codigo"] == "TE03")
    assert te03["huecos"] == ["2026-11-04"] and te03["ultima_fecha"] == "2026-11-06"
    provisional = _fuente(cuerpo, "riego_provisional")
    assert (provisional["estado"], provisional["ultima_fecha"]) == ("verde", "2026-11-07")

    clima = _fuente(cuerpo, "weatherlink")
    assert (clima["estado"], clima["ultima_fecha"], clima["huecos"]) == ("verde", "2026-11-07", ["2026-11-03"])
    suelo = _fuente(cuerpo, "phytech_suelo")
    assert (suelo["estado"], suelo["ultima_fecha"]) == ("naranja", "2026-11-05")
    assert _fuente(cuerpo, "phytech_planta")["estado"] == "verde"
    for informativa in ("ndvi", "pronostico"):
        fuente = _fuente(cuerpo, informativa)
        assert fuente["informativa"] is True and fuente["estado"] == "informativo"


def test_frescura_sin_datos_naranja_y_validaciones(client: TestClient, auth, modulo):
    cabeceras = auth("admin")
    cuerpo = client.get(f"{API}/datos/frescura", params={"modulo_id": modulo.id}, headers=cabeceras).json()
    for fuente in cuerpo["fuentes"][:5]:
        assert fuente["estado"] == "naranja" and fuente["ultima_fecha"] is None
    assert client.get(f"{API}/datos/frescura", params={"modulo_id": 999999}, headers=cabeceras).status_code == 404
    assert client.get(f"{API}/datos/frescura", params={"modulo_id": modulo.id, "dias": 61},
                      headers=cabeceras).status_code == 422
    assert client.get(f"{API}/datos/frescura", headers=cabeceras).status_code == 422


# --- Series ---------------------------------------------------------------------

def test_series_por_defecto_ultimos_14_dias_y_resoluciones(client: TestClient, auth, db, modulo):
    fundo_id = modulo.fundo_id
    db.add(AmbienteDiario(fundo_id=fundo_id, fecha=_dia(7), t_media=25.5, eto_mm=4.1, tiene_meteo=1,
                          hum_zona_radicular_cierre=31.0))
    db.add(AmbienteDiario(fundo_id=fundo_id, fecha=dt.date(2026, 10, 1), t_media=20.0, tiene_meteo=1))
    db.add(MeteoLectura(fundo_id=fundo_id, fecha_hora=dt.datetime(2026, 11, 7, 12, 30), temp=28.3,
                        origen=OrigenMeteo.weatherlink))
    db.add(PhytechPlantaDiario(fundo_id=fundo_id, plot_id=70208, project_id=907557, fecha=_dia(6),
                               mds_contraccion_um=240.0, et_mm=4.3))
    for capturado, t_max in ((_dia(7), 27.0), (HOY, 29.0)):
        db.add(PronosticoClima(fundo_id=fundo_id, project_id=907557, capturado_fecha=capturado, fecha=_dia(9),
                               t_max=t_max))
    db.commit()
    cabeceras = auth("programador")

    clima = client.get(f"{API}/datos/clima", headers=cabeceras).json()
    assert (clima["desde"], clima["hasta"], clima["resolucion"]) == ("2026-10-25", "2026-11-07", "diaria")
    assert [(p["fecha"], p["t_media"]) for p in clima["puntos"]] == [("2026-11-07", 25.5)]
    assert clima["unidades"]["t"] == "°C"
    detalle = client.get(f"{API}/datos/clima", params={"resolucion": "30min", "desde": "2026-11-07"},
                         headers=cabeceras).json()
    assert detalle["puntos"] == [{"fecha_hora": "2026-11-07T12:30:00", "temp": 28.3, "temp_max": None,
                                  "temp_min": None, "hr": None, "hr_max": None, "rad": None, "eto": None,
                                  "dpv": None, "viento": None, "lluvia": None, "origen": "weatherlink"}]
    suelo = client.get(f"{API}/datos/suelo", headers=cabeceras).json()
    assert suelo["puntos"][0]["hum_zona_radicular_cierre"] == 31.0
    planta = client.get(f"{API}/datos/planta", headers=cabeceras).json()
    assert [(p["fecha"], p["mds_contraccion_um"], p["et_mm"]) for p in planta["puntos"]] == [("2026-11-06", 240.0, 4.3)]
    pronostico = client.get(f"{API}/datos/pronostico", headers=cabeceras).json()
    assert pronostico["capturado_fecha"] == "2026-11-08" and pronostico["puntos"][0]["t_max"] == 29.0
    anterior = client.get(f"{API}/datos/pronostico", params={"capturado": "2026-11-07"}, headers=cabeceras).json()
    assert anterior["puntos"][0]["t_max"] == 27.0


@pytest.mark.parametrize("ruta, params", [
    ("/datos/frescura", {"fecha": "0001-01-01"}),
    ("/datos/frescura", {"fecha": "9999-12-31"}),
    ("/datos/clima", {"hasta": "0001-01-05"}),
    ("/datos/clima", {"desde": "9999-12-30", "hasta": "9999-12-31"}),
    ("/datos/suelo", {"desde": "0001-01-01", "hasta": "0001-01-02", "resolucion": "horaria"}),
    ("/riego", {"hasta": "0001-01-01"}),
    ("/riego", {"desde": "9999-12-31", "hasta": "9999-12-31"}),
])
def test_fechas_extremas_dan_422_y_no_500(client: TestClient, auth, modulo, ruta, params):
    respuesta = client.get(f"{API}{ruta}", params={"modulo_id": modulo.id, **params}, headers=auth("admin"))
    assert respuesta.status_code == 422, respuesta.text
    assert "2017-01-01" in str(respuesta.json()["detail"])


def test_series_validan_el_rango(client: TestClient, auth):
    cabeceras = auth("admin")
    assert client.get(f"{API}/datos/clima", params={"desde": "2026-11-07", "hasta": "2026-11-01"},
                      headers=cabeceras).status_code == 422
    assert client.get(f"{API}/datos/clima", params={"resolucion": "30min", "desde": "2026-09-01"},
                      headers=cabeceras).status_code == 422  # detalle: máx. 31 días
    assert client.get(f"{API}/datos/suelo", params={"resolucion": "semanal"}, headers=cabeceras).status_code == 422


# --- Turnos ---------------------------------------------------------------------

def test_turnos_con_caudal_reciente(client: TestClient, auth, db, modulo, turnos):
    te01 = turnos[0]
    _registro(db, modulo, te01, _dia(5), m3=300.0, minutos=90.0)   # 200 m3/h
    _registro(db, modulo, te01, _dia(6), m3=330.0, minutos=90.0)   # 220 m3/h
    _registro(db, modulo, te01, _dia(7), EstadoRiego.provisional, m3=999.0)  # provisional: no cuenta
    db.commit()
    cuerpo = client.get(f"{API}/modulos/{modulo.id}/turnos", headers=auth("programador")).json()
    assert [t["codigo"] for t in cuerpo] == [t.codigo for t in turnos]
    primero = cuerpo[0]
    assert primero["caudal_m3h"] == pytest.approx(210.0) and primero["ciclos_considerados"] == 2
    assert primero["ultimo_riego_aplicado"] == "2026-11-06"
    assert primero["area_ha"] == te01.area_ha and primero["valvula_controlador"] == te01.valvula_controlador
    assert cuerpo[1]["caudal_m3h"] is None and cuerpo[1]["ciclos_considerados"] == 0
    assert client.get(f"{API}/modulos/999999/turnos", headers=auth("admin")).status_code == 404
