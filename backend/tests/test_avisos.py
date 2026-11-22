"""Avisos del copiloto por Telegram: cambio de nivel del MDS, ingesta fallida y riego sin respuesta
del suelo; su confirmación (sin repetir) y el contrato con el flujo de n8n."""

from __future__ import annotations

import datetime as dt
import json
import re

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import settings
from app.models import Auditoria, IngestaCorrida
from app.models.enums import DisparoIngesta, EstadoIngesta
from app.services import avisos_service
from tests.conftest import API
from tests.test_copiloto import (  # noqa: F401 - fixtures y ayudas compartidas
    AYER,
    FLUJOS,
    HOY,
    _ambiente,
    _historial_suelo,
    _riego,
    _ruta,
    _suelo,
    agente,
    modulo,
    token,
    turnos,
)


@pytest.fixture(autouse=True)
def reloj():
    with time_machine.travel("2026-11-08 10:00 -05:00", tick=False):
        yield


@pytest.fixture(autouse=True)
def horario_ingesta(monkeypatch):
    monkeypatch.setattr(settings, "ingesta_hora", "05:00")
    monkeypatch.setattr(settings, "copiloto_gracia_ingesta_min", 30)
    monkeypatch.setattr(settings, "scheduler_enabled", False)


def _avisos(db, modulo, **kwargs) -> dict[str, dict]:
    db.flush()
    return {a["clave"]: a for a in avisos_service.avisos(db, modulo, **kwargs)}


def _de(avisos: dict[str, dict], codigo: str) -> list[dict]:
    return [a for a in avisos.values() if a["codigo"] == codigo]


def _corrida(db, fuente: str, estado: EstadoIngesta, errores: list | None = None) -> None:
    db.add(IngestaCorrida(fuente=fuente, disparo=DisparoIngesta.programado, fecha_programada=HOY, estado=estado,
                          errores=errores or []))


# --- 1. Cambio de nivel del MDS -------------------------------------------------------


def test_mds_sube_de_moderado_a_alto(db, modulo):
    _ambiente(db, modulo, AYER - dt.timedelta(days=1), mds_contraccion_um=205)
    _ambiente(db, modulo, AYER, mds_contraccion_um=241.4, eto_mm=4.12)
    [aviso] = _de(_avisos(db, modulo), "mds_nivel")
    assert aviso["clave"] == f"mds_nivel:{modulo.id}:{AYER.isoformat()}:alto"
    assert aviso["severidad"] == "media" and aviso["icono"] == "🟠" and aviso["destino"] == "campo"
    assert aviso["titulo"] == "El MDS subió a estrés alto"
    assert "241 µm, con ETo de 4.1 mm" in aviso["detalle"] and "205 µm (estrés moderado)" in aviso["detalle"]
    assert "Revisa que el plan de hoy cubra la demanda" in aviso["detalle"]
    assert aviso["valores"]["sube"] is True and aviso["enviado"] is False


@pytest.mark.parametrize(("antes", "ahora", "nivel", "severidad"), [
    (150, 195, "moderado", "info"), (200, 260, "critico", "alta"), (230, 120, "sin_estres", "info"),
    (260, 225, "alto", "info"),
])
def test_cada_cambio_de_nivel(db, modulo, antes, ahora, nivel, severidad):
    _ambiente(db, modulo, AYER - dt.timedelta(days=1), mds_contraccion_um=antes)
    _ambiente(db, modulo, AYER, mds_contraccion_um=ahora)
    [aviso] = _de(_avisos(db, modulo), "mds_nivel")
    assert aviso["valores"]["nivel"] == nivel and aviso["severidad"] == severidad
    assert ("subió" in aviso["titulo"]) is (ahora > antes)


@pytest.mark.parametrize("dias", [
    {AYER - dt.timedelta(days=1): 225, AYER: 245},  # mismo nivel (alto)
    {AYER: 260},  # un solo día
    {AYER - dt.timedelta(days=5): 150, AYER - dt.timedelta(days=4): 260},  # dato viejo
])
def test_mds_sin_cambio_o_sin_datos_recientes_no_avisa(db, modulo, dias):
    for fecha, mds in dias.items():
        _ambiente(db, modulo, fecha, mds_contraccion_um=mds)
    assert _de(_avisos(db, modulo), "mds_nivel") == []


def test_mds_compara_con_el_dia_anterior_con_dato(db, modulo):
    _ambiente(db, modulo, AYER - dt.timedelta(days=2), mds_contraccion_um=150)
    _ambiente(db, modulo, AYER - dt.timedelta(days=1), eto_mm=3.0)  # sin MDS ese día
    _ambiente(db, modulo, AYER, mds_contraccion_um=230)
    [aviso] = _de(_avisos(db, modulo), "mds_nivel")
    assert aviso["valores"]["fecha_anterior"] == AYER - dt.timedelta(days=2)


# --- 2. Ingesta programada ----------------------------------------------------------------


def test_ingesta_con_error_avisa_con_el_mensaje(db, modulo):
    _corrida(db, "weatherlink", EstadoIngesta.error, [{"tipo": "http", "mensaje": "HTTP 503 en /current"}])
    _corrida(db, "ndvi", EstadoIngesta.error, [{"tipo": "http", "mensaje": "sin imágenes"}])
    _corrida(db, "phytech_suelo", EstadoIngesta.parcial)
    avisos = {a["valores"]["fuente"]: a for a in _de(_avisos(db, modulo), "ingesta_fallida")}
    assert set(avisos) == {"weatherlink", "ndvi", "phytech_suelo"}
    clima = avisos["weatherlink"]
    assert clima["clave"] == f"ingesta_fallida:{modulo.id}:{HOY.isoformat()}:weatherlink"
    assert clima["severidad"] == "alta" and clima["destino"] == "sistema"
    assert clima["titulo"] == "La ingesta de WeatherLink (clima) falló"
    assert "Error: HTTP 503 en /current." in clima["detalle"] and "05:00" in clima["detalle"]
    assert avisos["ndvi"]["severidad"] == "media"  # informativa
    assert avisos["phytech_suelo"]["titulo"] == "La ingesta de Phytech suelo quedó incompleta"


def test_ingesta_no_avisa_antes_de_la_gracia(db, modulo):
    _corrida(db, "weatherlink", EstadoIngesta.error)
    antes = dt.datetime(2026, 11, 8, 5, 29, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
    assert _de(_avisos(db, modulo, ahora=antes), "ingesta_fallida") == []
    assert len(_de(_avisos(db, modulo, ahora=antes.replace(minute=30)), "ingesta_fallida")) == 1


def test_ingesta_que_no_corrio_solo_con_programador(db, modulo, monkeypatch):
    assert _de(_avisos(db, modulo), "ingesta_fallida") == []
    monkeypatch.setattr(settings, "scheduler_enabled", True)
    avisos = {a["valores"]["fuente"]: a for a in _de(_avisos(db, modulo), "ingesta_fallida")}
    assert set(avisos) == {"weatherlink", "phytech_suelo", "phytech_planta", "ndvi", "pronostico", "galileo_riego"}
    assert avisos["phytech_planta"]["titulo"] == "La ingesta de Phytech planta (MDS) no corrió hoy"
    assert avisos["phytech_planta"]["severidad"] == "alta" and avisos["pronostico"]["severidad"] == "media"


def test_ingesta_ok_pero_sin_datos_de_ayer(db, modulo, turnos):
    for fuente in ("weatherlink", "phytech_planta", "galileo_riego", "phytech_suelo"):
        _corrida(db, fuente, EstadoIngesta.ok)
    _ambiente(db, modulo, AYER, tiene_meteo=1, eto_mm=3.0, hum_zona_radicular_cierre=30.0)  # clima y suelo al día
    _ambiente(db, modulo, AYER - dt.timedelta(days=3), tiene_planta=1, mds_contraccion_um=200)
    _riego(db, modulo, turnos, AYER - dt.timedelta(days=1), 40.0)  # 1 día de atraso: se tolera
    avisos = {a["valores"]["fuente"]: a for a in _de(_avisos(db, modulo), "ingesta_fallida")}
    assert set(avisos) == {"phytech_planta"}
    aviso = avisos["phytech_planta"]
    assert aviso["titulo"] == "Phytech planta (MDS): la ingesta corrió, pero faltan datos"
    assert aviso["severidad"] == "media" and aviso["valores"]["dias_atraso"] == 3
    assert "04/11/2026 (3 día(s) de atraso respecto de 07/11/2026)" in aviso["detalle"]


def test_riego_con_dos_dias_de_atraso_avisa(db, modulo, turnos):
    _corrida(db, "galileo_riego", EstadoIngesta.ok)
    _riego(db, modulo, turnos, AYER - dt.timedelta(days=2), 40.0)
    [aviso] = [a for a in _de(_avisos(db, modulo), "ingesta_fallida") if a["valores"]["fuente"] == "galileo_riego"]
    assert aviso["valores"]["dias_atraso"] == 2 and "05/11/2026" in aviso["detalle"]


# --- 3. Riego sin respuesta del suelo -----------------------------------------------------


def test_riego_sin_respuesta_con_m3_m3ha_y_eto(db, modulo, turnos):
    _historial_suelo(db, modulo, turnos)
    _riego(db, modulo, turnos, AYER, 45.0)
    _suelo(db, modulo, AYER, 0.4)
    _ambiente(db, modulo, AYER, eto_mm=4.3)
    [aviso] = _de(_avisos(db, modulo), "riego_sin_respuesta")
    assert aviso["clave"] == f"riego_sin_respuesta:{modulo.id}:{AYER.isoformat()}:suelo"
    assert aviso["severidad"] == "alta" and aviso["destino"] == "campo"
    area = sum(t.area_ha for t in turnos if t.activo)
    assert f"{45.0 * area:,.0f} m³ (45.0 m³/ha) con ETo de 4.3 mm" in aviso["detalle"]
    assert "0.40 % vol." in aviso["detalle"] and "~3.0 % vol." in aviso["detalle"]


def test_respuesta_normal_del_suelo_no_avisa(db, modulo, turnos):
    _historial_suelo(db, modulo, turnos)
    _riego(db, modulo, turnos, AYER, 45.0)
    _suelo(db, modulo, AYER, 2.9)
    assert _de(_avisos(db, modulo), "riego_sin_respuesta") == []


# --- API: pendientes y confirmación ---------------------------------------------------


def _con_un_aviso(db, modulo) -> str:
    _ambiente(db, modulo, AYER - dt.timedelta(days=1), mds_contraccion_um=150)
    _ambiente(db, modulo, AYER, mds_contraccion_um=230)
    db.commit()
    return f"mds_nivel:{modulo.id}:{AYER.isoformat()}:alto"


def test_confirmar_no_repite_y_queda_en_la_auditoria(client: TestClient, db, modulo, token):
    clave = _con_un_aviso(db, modulo)
    pendientes = client.get(f"{API}/copiloto/avisos", params={"pendientes": True}, headers=agente(token)).json()
    assert [a["clave"] for a in pendientes["avisos"]] == [clave]
    assert pendientes["modulo"]["id"] == modulo.id

    respuesta = client.post(f"{API}/copiloto/avisos/confirmar", json={"claves": [clave, clave]}, headers=agente(token))
    assert respuesta.status_code == 200, respuesta.text
    assert respuesta.json() == {"confirmadas": 1, "ya_confirmadas": 0}
    otra = client.post(f"{API}/copiloto/avisos/confirmar", json={"claves": [clave]}, headers=agente(token))
    assert otra.json() == {"confirmadas": 0, "ya_confirmadas": 1}

    assert client.get(f"{API}/copiloto/avisos", params={"pendientes": True}, headers=agente(token)).json()["avisos"] == []
    todos = client.get(f"{API}/copiloto/avisos", headers=agente(token)).json()["avisos"]
    assert [(a["clave"], a["enviado"]) for a in todos] == [(clave, True)]
    fila = db.scalars(select(Auditoria).where(Auditoria.accion == "aviso_enviado")).one()
    assert fila.entidad == "copiloto_aviso" and fila.entidad_id == clave
    assert fila.username == "agente:n8n-prueba"
    assert fila.detalle == {"codigo": "mds_nivel", "modulo_id": modulo.id, "fecha": AYER.isoformat(), "detalle": "alto"}


@pytest.mark.parametrize("rol", ("admin", "encargado", "subgerente"))
def test_usuarios_ven_los_avisos_pero_no_los_confirman(client: TestClient, auth, rol):
    cabeceras = auth(rol)
    assert client.get(f"{API}/copiloto/avisos", headers=cabeceras).status_code == 200
    respuesta = client.post(f"{API}/copiloto/avisos/confirmar", json={"claves": ["mds_nivel:1:2026-11-07:alto"]},
                            headers=cabeceras)
    assert respuesta.status_code == 403


@pytest.mark.parametrize("claves", [
    [], ["cualquier cosa"], ["mds_nivel:1:2026-11-07:Alto"], ["otro_codigo:1:2026-11-07:x"],
    ["mds_nivel:1:2026-11-07:" + "x" * 21], ["x"] * 51,
])
def test_claves_invalidas_422(client: TestClient, token, claves):
    respuesta = client.post(f"{API}/copiloto/avisos/confirmar", json={"claves": claves}, headers=agente(token))
    assert respuesta.status_code == 422


def test_las_claves_caben_en_la_auditoria():
    largo = len("ingesta_fallida:999999:2026-11-07:") + 20
    assert largo <= 60


# --- Contrato con el flujo de n8n ---------------------------------------------------------


def test_flujo_de_avisos_llama_rutas_validas(client: TestClient, db, modulo, token):
    clave = _con_un_aviso(db, modulo)
    flujo = json.loads((FLUJOS / "avisos.json").read_text(encoding="utf-8"))
    http = {n["name"]: n for n in flujo["nodes"] if n["type"] == "n8n-nodes-base.httpRequest"}
    consulta = http["Avisos pendientes"]["parameters"]
    query = {q["name"]: q["value"] for q in consulta["queryParameters"]["parameters"]}
    respuesta = client.get(_ruta(consulta["url"]), params=query, headers=agente(token))
    assert respuesta.status_code == 200 and [a["clave"] for a in respuesta.json()["avisos"]] == [clave]

    confirmar = http["Confirmar enviados"]
    assert confirmar["executeOnce"] is True and confirmar["parameters"]["method"] == "POST"
    assert re.search(r"\$\('Mensajes'\)\.all\(\)", confirmar["parameters"]["jsonBody"])
    respuesta = client.post(_ruta(confirmar["parameters"]["url"]), json={"claves": [clave]}, headers=agente(token))
    assert respuesta.status_code == 200, respuesta.text
    for nodo in http.values():
        assert nodo["credentials"]["httpHeaderAuth"]["name"] == "Token agente copiloto"


@pytest.mark.parametrize("archivo", ("agente_telegram.json", "devlum/agente_telegram.json"))
def test_comando_avisos_del_bot_llama_una_ruta_valida(client: TestClient, token, archivo):
    nodos = {n["name"]: n for n in json.loads((FLUJOS / archivo).read_text(encoding="utf-8"))["nodes"]}
    consulta = nodos["Avisos de hoy"]["parameters"]
    assert client.get(_ruta(consulta["url"]), headers=agente(token)).status_code == 200
