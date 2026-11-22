"""Copiloto agrónomo: token del agente, permisos, sugerencias con aprobación, auditoría y reglas
de alertas (estrés, respuesta del suelo, desvío plan vs real, plan sin generar, demanda alta)."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    AmbienteDiario,
    Auditoria,
    PhytechSueloHorario,
    PronosticoClima,
    RiegoCiclo,
    RiegoRegistro,
    Turno,
)
from app.models.enums import EstadoRiego, OrigenRiego
from app.repositories import datos_campo as repo_datos
from app.services import agente_service, copiloto_service
from app.services.copiloto_service import Lector
from tests.conftest import API

HOY = dt.date(2026, 11, 8)
AYER = HOY - dt.timedelta(days=1)
PROJECT_ID = 907557
PLOT_ID = 70208


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


@pytest.fixture
def token(db):
    """Token en claro de un agente recién creado."""
    _fila, texto = agente_service.crear(db, "n8n-prueba")
    db.commit()
    return texto


def agente(token: str) -> dict[str, str]:
    return {"X-Token-Agente": token}


def _riego(db, modulo, turnos, fecha: dt.date, m3ha: float) -> None:
    for t in turnos:
        registro = RiegoRegistro(modulo_id=modulo.id, turno_id=t.id, fecha=fecha, version=1, vigente=True,
                                 estado=EstadoRiego.aplicado, origen=OrigenRiego.historico, contenido_sha256="0" * 64)
        registro.ciclos = [RiegoCiclo(inicio_min=360, fin_min=450, duracion_min=90, riego_m3=m3ha * t.area_ha,
                                      riego_m3ha=m3ha, area_ha=t.area_ha, hora_inicio="06:00", hora_fin="07:30")]
        db.add(registro)


def _suelo(db, modulo, fecha: dt.date, subida: float) -> None:
    """24 lecturas: 23 % vol. de madrugada y un pico de ``23 + subida`` a media mañana."""
    for hora in range(24):
        valor = 23.0 + (subida if 9 <= hora <= 12 else 0.0)
        db.add(PhytechSueloHorario(fundo_id=modulo.fundo_id, plot_id=PLOT_ID, project_id=PROJECT_ID,
                                   fecha_hora=dt.datetime.combine(fecha, dt.time(hora)), hay_dato=True,
                                   hum_zona_radicular=valor))


def _ambiente(db, modulo, fecha: dt.date, **valores) -> None:
    db.add(AmbienteDiario(fundo_id=modulo.fundo_id, fecha=fecha, **valores))


def _alertas(db, modulo) -> dict[str, dict]:
    db.flush()
    return {a["codigo"]: a for a in copiloto_service.resumen(db, modulo, HOY, Lector())["alertas"]}


# --- Token y permisos ---------------------------------------------------------------


def test_token_solo_guarda_el_hash_y_se_muestra_una_vez(db):
    fila, texto = agente_service.crear(db, "N8N-Otro")
    assert texto.startswith("rga_") and len(texto) > 40
    assert fila.nombre == "n8n-otro"
    assert fila.token_hash != texto and texto not in fila.token_hash
    assert fila.prefijo == texto[:10]
    assert agente_service.autenticar(db, texto).id == fila.id
    assert agente_service.autenticar(db, texto + "x") is None


def test_token_con_nombre_repetido_o_invalido(db, token):
    from app.core.errores import Conflicto, DatosInvalidos

    with pytest.raises(Conflicto):
        agente_service.crear(db, "n8n-prueba")
    with pytest.raises(DatosInvalidos):
        agente_service.crear(db, "a b")


def test_agente_lee_el_resumen_y_queda_auditado(client: TestClient, db, token):
    respuesta = client.get(f"{API}/copiloto/resumen", headers=agente(token))
    assert respuesta.status_code == 200, respuesta.text
    cuerpo = respuesta.json()
    assert cuerpo["modulo"]["codigo"] == "EN01-MOD5"
    assert cuerpo["fecha"] == HOY.isoformat()
    assert {"plan_hoy", "plan_manana", "ayer", "contexto", "pronostico", "alertas", "umbrales"} <= cuerpo.keys()
    fila = db.scalars(select(Auditoria).where(Auditoria.accion == "consulta_agente")).one()
    assert fila.username == "agente:n8n-prueba"
    assert fila.detalle == {"metodo": "GET", "ruta": "/api/v1/copiloto/resumen"}
    assert token not in str(fila.detalle)


@pytest.mark.parametrize("rol", ("admin", "encargado", "subgerente"))
def test_usuarios_con_acceso_al_copiloto(client: TestClient, auth, rol):
    cabeceras = auth(rol)
    for ruta in ("/copiloto/resumen", "/copiloto/alertas", "/copiloto/plan", "/copiloto/agua?turno=TE01",
                 "/copiloto/clima", "/copiloto/pronostico", "/copiloto/modulos", "/copiloto/sugerencias"):
        respuesta = client.get(API + ruta, headers=cabeceras)
        assert respuesta.status_code == 200, (ruta, respuesta.text)


def test_programador_y_anonimo_no_entran(client: TestClient, auth):
    assert client.get(f"{API}/copiloto/resumen").status_code == 401
    assert client.get(f"{API}/copiloto/resumen", headers=auth("programador")).status_code == 403


def test_token_invalido_o_revocado_401(client: TestClient, db, token):
    assert client.get(f"{API}/copiloto/resumen", headers=agente("rga_inventado")).status_code == 401
    assert client.get(f"{API}/copiloto/resumen", headers=agente("otra-cosa")).status_code == 401
    agente_service.revocar(db, "n8n-prueba")
    db.commit()
    assert client.get(f"{API}/copiloto/resumen", headers=agente(token)).status_code == 401


def test_turno_inexistente_422(client: TestClient, token):
    respuesta = client.get(f"{API}/copiloto/agua?turno=TE99", headers=agente(token))
    assert respuesta.status_code == 422


# --- Sugerencias --------------------------------------------------------------------

SUGERENCIA = {"fecha": AYER.isoformat(), "turno_codigo": "te03", "tipo": "revisar_equipo",
              "alerta_codigo": "riego_sin_respuesta", "titulo": "Revisar la válvula del TE03",
              "detalle": "El suelo no respondió al riego de ayer."}


def test_agente_crea_sugerencia_y_no_la_duplica(client: TestClient, db, token):
    primera = client.post(f"{API}/copiloto/sugerencias", json=SUGERENCIA, headers=agente(token))
    assert primera.status_code == 201, primera.text
    assert primera.json()["estado"] == "pendiente"
    assert primera.json()["turno_codigo"] == "TE03"
    assert primera.json()["propuesta_por"] == "agente:n8n-prueba"
    assert primera.json()["duplicada"] is False
    segunda = client.post(f"{API}/copiloto/sugerencias", json=SUGERENCIA, headers=agente(token))
    assert segunda.status_code == 200
    assert segunda.json()["duplicada"] is True and segunda.json()["id"] == primera.json()["id"]
    assert db.scalars(select(Auditoria).where(Auditoria.accion == "sugerencia_creada")).one().username == "agente:n8n-prueba"


def test_solo_el_agente_crea_sugerencias(client: TestClient, auth):
    assert client.post(f"{API}/copiloto/sugerencias", json=SUGERENCIA, headers=auth("encargado")).status_code == 403


@pytest.mark.parametrize("cambio", ({"turno_codigo": "TE99"}, {"fecha": "2026-12-31"}, {"tipo": "publicar"},
                                    {"titulo": "x"}, {"extra": 1}))
def test_sugerencia_invalida_422(client: TestClient, token, cambio):
    respuesta = client.post(f"{API}/copiloto/sugerencias", json={**SUGERENCIA, **cambio}, headers=agente(token))
    assert respuesta.status_code == 422, respuesta.text


def test_encargado_aprueba_y_no_se_resuelve_dos_veces(client: TestClient, db, token, auth):
    creada = client.post(f"{API}/copiloto/sugerencias", json=SUGERENCIA, headers=agente(token)).json()
    encargado = auth("encargado")
    aprobada = client.post(f"{API}/copiloto/sugerencias/{creada['id']}/aprobar", json={"comentario": "Voy a campo"},
                           headers=encargado)
    assert aprobada.status_code == 200, aprobada.text
    assert aprobada.json()["estado"] == "aprobada"
    assert aprobada.json()["resuelto_por"] == "Usuario encargado_prueba"
    otra_vez = client.post(f"{API}/copiloto/sugerencias/{creada['id']}/descartar", json={"comentario": "no"},
                           headers=encargado)
    assert otra_vez.status_code == 409
    pendientes = client.get(f"{API}/copiloto/sugerencias?estado=pendiente", headers=encargado).json()
    assert pendientes == []


def test_descartar_exige_motivo_y_subgerente_no_resuelve(client: TestClient, token, auth):
    creada = client.post(f"{API}/copiloto/sugerencias", json=SUGERENCIA, headers=agente(token)).json()
    ruta = f"{API}/copiloto/sugerencias/{creada['id']}"
    assert client.post(f"{ruta}/aprobar", headers=auth("subgerente")).status_code == 403
    assert client.post(f"{ruta}/aprobar", headers=agente(token)).status_code == 401
    admin = auth("admin")
    assert client.post(f"{ruta}/descartar", json={}, headers=admin).status_code == 422
    descartada = client.post(f"{ruta}/descartar", json={"comentario": "Ya se revisó ayer"}, headers=admin)
    assert descartada.status_code == 200 and descartada.json()["estado"] == "descartada"


# --- Reglas ---------------------------------------------------------------------------


def test_sin_cronogramas_alerta_plan_de_hoy(db, modulo):
    alertas = _alertas(db, modulo)
    assert alertas["plan_hoy_sin_generar"]["severidad"] == "alta"
    assert alertas["plan_manana_sin_generar"]["severidad"] == "info"  # antes de las 16:00


def test_estres_mds_y_suelo_dias_seguidos(db, modulo):
    _ambiente(db, modulo, AYER - dt.timedelta(days=2), mds_contraccion_um=150, eto_mm=3.0,
              hum_zona_radicular_cierre=32, hum_linea_estres_cierre=31)
    _ambiente(db, modulo, AYER - dt.timedelta(days=1), mds_contraccion_um=230, eto_mm=3.5,
              hum_zona_radicular_cierre=30, hum_linea_estres_cierre=31)
    _ambiente(db, modulo, AYER, mds_contraccion_um=260, eto_mm=4.0,
              hum_zona_radicular_cierre=30.2, hum_linea_estres_cierre=31)
    alertas = _alertas(db, modulo)
    assert alertas["estres_mds"]["severidad"] == "alta"
    assert alertas["estres_mds"]["valores"]["dias"] == 2
    assert alertas["estres_mds"]["valores"]["nivel"] == "critico"
    assert alertas["estres_suelo"]["valores"]["dias"] == 2


def test_un_solo_dia_de_estres_no_alerta(db, modulo):
    _ambiente(db, modulo, AYER - dt.timedelta(days=1), mds_contraccion_um=150)
    _ambiente(db, modulo, AYER, mds_contraccion_um=260)
    assert "estres_mds" not in _alertas(db, modulo)


def _historial_suelo(db, modulo, turnos, dias: int = 10) -> None:
    for i in range(2, dias + 2):
        fecha = AYER - dt.timedelta(days=i)
        _riego(db, modulo, turnos, fecha, 45.0)
        _suelo(db, modulo, fecha, 3.0)


def test_riego_sin_respuesta_del_suelo(db, modulo, turnos):
    _historial_suelo(db, modulo, turnos)
    _riego(db, modulo, turnos, AYER, 45.0)
    _suelo(db, modulo, AYER, 0.4)
    alerta = _alertas(db, modulo)["riego_sin_respuesta"]
    assert alerta["severidad"] == "alta"
    assert alerta["fecha"] == AYER
    assert alerta["valores"]["subida_normal_pct_vol"] == 3.0


def test_humedad_sin_riego_registrado(db, modulo, turnos):
    _historial_suelo(db, modulo, turnos)
    _suelo(db, modulo, AYER, 3.2)
    alertas = _alertas(db, modulo)
    assert "humedad_sin_riego" in alertas
    assert "riego_sin_respuesta" not in alertas


def test_respuesta_normal_no_alerta(db, modulo, turnos):
    _historial_suelo(db, modulo, turnos)
    _riego(db, modulo, turnos, AYER, 45.0)
    _suelo(db, modulo, AYER, 2.8)
    alertas = _alertas(db, modulo)
    assert "riego_sin_respuesta" not in alertas and "humedad_sin_riego" not in alertas


def test_desvio_plan_real_por_turno():
    dias = [{"fecha": AYER, "turnos": [
        {"turno_codigo": "TE01", "estado_riego": "aplicado", "sin_riego": False, "propuesto_m3ha": 40.0,
         "propuesto_m3": 400.0, "aplicado_m3ha": 41.0, "aplicado_m3": 410.0},
        {"turno_codigo": "TE02", "estado_riego": "aplicado", "sin_riego": False, "propuesto_m3ha": 40.0,
         "propuesto_m3": 400.0, "aplicado_m3ha": 30.0, "aplicado_m3": 300.0},
        {"turno_codigo": "TE03", "estado_riego": "aplicado", "sin_riego": True, "propuesto_m3ha": 40.0,
         "propuesto_m3": 400.0, "aplicado_m3ha": None, "aplicado_m3": None},
        {"turno_codigo": "TE04", "estado_riego": "provisional", "sin_riego": False, "propuesto_m3ha": 40.0,
         "propuesto_m3": 400.0, "aplicado_m3ha": 10.0, "aplicado_m3": 100.0},
    ]}]
    alertas = {a["turno_codigo"]: a for a in copiloto_service._alertas_desvio(dias)}
    assert set(alertas) == {"TE02", "TE03"}
    assert alertas["TE02"]["severidad"] == "media" and alertas["TE02"]["valores"]["desvio_pct"] == -25
    assert alertas["TE03"]["severidad"] == "alta" and alertas["TE03"]["valores"]["desvio_pct"] == -100


def test_demanda_alta_por_pronostico(db, modulo):
    for i in range(5):
        _ambiente(db, modulo, AYER - dt.timedelta(days=i), eto_mm=3.0)
    for i, eto in enumerate((3.2, 4.6, 3.1)):
        db.add(PronosticoClima(fundo_id=modulo.fundo_id, project_id=PROJECT_ID, capturado_fecha=HOY,
                               fecha=HOY + dt.timedelta(days=i), eto_mm=eto, t_max=29))
    alerta = _alertas(db, modulo)["demanda_alta"]
    assert alerta["severidad"] == "info"
    assert alerta["valores"]["eto_mm"] == 4.6


def test_nivel_mds():
    assert copiloto_service.nivel_mds(None) is None
    assert copiloto_service.nivel_mds(100) == "sin_estres"
    assert copiloto_service.nivel_mds(190) == "moderado"
    assert copiloto_service.nivel_mds(220) == "alto"
    assert copiloto_service.nivel_mds(250) == "critico"


def test_agua_sin_cronograma_no_inventa_cero_propuesto(db, modulo, turnos):
    _riego(db, modulo, turnos, AYER, 45.0)
    db.flush()
    datos = copiloto_service.agua(db, modulo, AYER, AYER, Lector(), "te01")
    assert datos["totales"]["propuesto_m3"] is None and datos["totales"]["propuesto_m3ha"] is None
    assert datos["totales"]["aplicado_m3ha"] == 45.0
    assert datos["por_turno"][0]["dias_con_riego"] == 1 and datos["por_turno"][0]["dias_con_propuesta"] == 0


def test_sugerencia_con_campos_vacios_como_los_manda_n8n(client: TestClient, token):
    cuerpo = {**SUGERENCIA, "turno_codigo": "", "alerta_codigo": "null", "detalle": " "}
    respuesta = client.post(f"{API}/copiloto/sugerencias", json=cuerpo, headers=agente(token))
    assert respuesta.status_code == 201, respuesta.text
    assert respuesta.json()["turno_codigo"] is None and respuesta.json()["alerta_codigo"] is None


# --- Contrato con los flujos de n8n (automatizacion/n8n/flujos) ----------------------


FLUJOS = Path(__file__).resolve().parents[2] / "automatizacion" / "n8n" / "flujos"
# Lo que el agente completaría en cada $fromAI(...), siempre como texto (así lo manda n8n).
VALORES_IA = {"fecha": AYER.isoformat(), "desde": (AYER - dt.timedelta(days=6)).isoformat(),
              "hasta": AYER.isoformat(), "turno": "te02", "estado": "pendiente", "tipo": "revisar_equipo",
              "titulo": "Revisar la válvula del TE02", "detalle": "Prueba del contrato", "turno_codigo": "",
              "alerta_codigo": ""}


def _ruta(url: str) -> str:
    return re.sub(r"^=\{\{.*?\}\}/api/v1", "/api/v1", url)


def _valor(expresion: str) -> str:
    return VALORES_IA[re.search(r"\$fromAI\('(\w+)'", expresion).group(1)]


def _nodos(archivo: str, tipo: str) -> list[dict]:
    return [n for n in json.loads((FLUJOS / archivo).read_text(encoding="utf-8"))["nodes"] if n["type"] == tipo]


FLUJOS_AGENTE = ("agente_telegram.json", "agente_chat_prueba.json", "devlum/agente_telegram.json",
                 "devlum/agente_chat_prueba.json")


@pytest.mark.parametrize("archivo", FLUJOS_AGENTE)
def test_cada_herramienta_del_agente_responde(client: TestClient, token, archivo):
    herramientas = _nodos(archivo, "n8n-nodes-base.httpRequestTool")
    assert {h["name"] for h in herramientas} == {
        "resumen_del_dia", "plan_de_un_dia", "agua_del_modulo", "agua_de_un_turno", "clima_y_planta",
        "sugerencias_pendientes", "crear_sugerencia"}
    for h in herramientas:
        p = h["parameters"]
        assert h["credentials"]["httpHeaderAuth"]["name"] == "Token agente copiloto"
        query = {q["name"]: _valor(q["value"]) for q in p.get("queryParameters", {}).get("parameters", [])}
        cuerpo = {b["name"]: _valor(b["value"]) for b in p.get("bodyParameters", {}).get("parameters", [])}
        if p["method"] == "POST":
            respuesta = client.post(_ruta(p["url"]), json=cuerpo, headers=agente(token))
        else:
            respuesta = client.get(_ruta(p["url"]), params=query, headers=agente(token))
        assert respuesta.status_code in (200, 201), (h["name"], respuesta.text)


@pytest.mark.parametrize("archivo", ("informe_diario.json", "devlum/informe_diario.json"))
def test_flujo_del_informe_llama_rutas_validas(client: TestClient, token, archivo):
    http = {n["name"]: n["parameters"] for n in _nodos(archivo, "n8n-nodes-base.httpRequest")}
    assert client.get(_ruta(http["Resumen del copiloto"]["url"]), headers=agente(token)).status_code == 200
    sugerencia = {"modulo_id": None, "fecha": AYER.isoformat(), "turno_codigo": None, "tipo": "ajustar_riego",
                  "alerta_codigo": "estres_mds", "titulo": "Estrés crítico por MDS", "detalle": "MDS 253 µm"}
    respuesta = client.post(_ruta(http["Crear sugerencia"]["url"]), json=sugerencia, headers=agente(token))
    assert respuesta.status_code == 201, respuesta.text


def test_alertas_distintas_del_mismo_codigo_no_se_pisan(client: TestClient, token):
    base = {"fecha": AYER.isoformat(), "tipo": "revisar_datos", "alerta_codigo": "datos_atrasados"}
    ids = {client.post(f"{API}/copiloto/sugerencias", json={**base, "titulo": t}, headers=agente(token)).json()["id"]
           for t in ("WeatherLink (clima): datos atrasados", "Phytech suelo: datos atrasados",
                     "PHYTECH SUELO: datos atrasados")}
    assert len(ids) == 2  # el título no distingue mayúsculas


def test_dos_peticiones_iguales_a_la_vez_no_duplican(client: TestClient, db, token, monkeypatch):
    from app.repositories import copiloto as repo_copiloto
    from app.models import CopilotoSugerencia

    primera = client.post(f"{API}/copiloto/sugerencias", json=SUGERENCIA, headers=agente(token)).json()
    original = repo_copiloto.pendiente_igual
    llamadas = []

    def sin_ver_la_primera(*args, **kwargs):  # simula la carrera: la consulta previa no la encuentra
        llamadas.append(1)
        return None if len(llamadas) == 1 else original(*args, **kwargs)

    monkeypatch.setattr(repo_copiloto, "pendiente_igual", sin_ver_la_primera)
    segunda = client.post(f"{API}/copiloto/sugerencias", json=SUGERENCIA, headers=agente(token))
    assert segunda.status_code == 200, segunda.text
    assert segunda.json()["id"] == primera["id"] and segunda.json()["duplicada"] is True
    assert len(db.scalars(select(CopilotoSugerencia)).all()) == 1


@pytest.mark.parametrize("archivo", ("informe_diario.json", *FLUJOS_AGENTE, "devlum/informe_diario.json"))
def test_modelo_de_cada_flujo(archivo):
    """Anthropic directo o Devlum (compatible con OpenAI), siempre Claude Opus 5.5 y sin temperatura."""
    nodos = json.loads((FLUJOS / archivo).read_text(encoding="utf-8"))["nodes"]
    modelo = next(n for n in nodos if n["name"] == "Claude")
    assert modelo["parameters"]["model"]["value"] == "claude-opus-5-5"
    assert "temperature" not in modelo["parameters"]["options"]
    if archivo.startswith("devlum/"):
        assert modelo["type"] == "@n8n/n8n-nodes-langchain.lmChatOpenAi" and modelo["typeVersion"] == 1.2
        assert modelo["parameters"]["options"]["baseURL"] == "https://ai.devlumlabs.com/api/v1"
        assert modelo["credentials"] == {"openAiApi": {"id": "REEMPLAZAR", "name": "Devlum AI"}}
    else:
        assert modelo["type"] == "@n8n/n8n-nodes-langchain.lmChatAnthropic"
