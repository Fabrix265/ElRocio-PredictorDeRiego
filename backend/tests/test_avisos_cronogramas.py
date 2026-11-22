"""Avisos por Telegram de los cambios en los cronogramas (generar, regenerar, corregir, publicar,
anular…) con el plan completo, y el comando /plan del bot."""

from __future__ import annotations

import datetime as dt
import json

import pytest
import time_machine
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.models import (
    Auditoria,
    Cronograma,
    CronogramaCiclo,
    CronogramaEvento,
    CronogramaTurno,
    CronogramaVersion,
    MotivoCorreccion,
)
from app.models.enums import EstadoCronograma, OrigenVersion, TipoEventoCronograma
from app.services import avisos_service
from tests.conftest import API
from tests.test_copiloto import FLUJOS, _ruta, agente, modulo, token, turnos  # noqa: F401 - fixtures

AHORA = dt.datetime(2026, 11, 8, 10, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
MANANA = dt.date(2026, 11, 9)


@pytest.fixture(autouse=True)
def reloj():
    with time_machine.travel(AHORA, tick=False):
        yield


@pytest.fixture
def encargado(crear_usuario):
    return crear_usuario("ana.campo", rol="encargado", nombre="Ana Campos")


def _cronograma(db, modulo, fecha=MANANA, **valores) -> Cronograma:
    crono = Cronograma(modulo_id=modulo.id, fecha=fecha, **valores)
    db.add(crono)
    db.flush()
    return crono


def _version(db, crono, turnos, numero, origen=OrigenVersion.modelo, m3ha=None, ciclos=1, **extra):
    """Una versión con ``ciclos`` ciclos de 20 m³/ha por turno (o lo que diga ``m3ha``), desde las 06:00."""
    v = CronogramaVersion(cronograma_id=crono.id, numero=numero, origen=origen, **extra)
    db.add(v)
    db.flush()
    inicio = 360
    for t in turnos:
        valor = (m3ha or {}).get(t.codigo, 20.0)
        db.add(CronogramaTurno(version_id=v.id, turno_id=t.id, n_ciclos=ciclos, area_ha=t.area_ha))
        for c in range(1, ciclos + 1):
            db.add(CronogramaCiclo(
                version_id=v.id, turno_id=t.id, ciclo=c, riego_m3ha=valor / ciclos, riego_m3=valor / ciclos * t.area_ha,
                duracion_min=60, inicio_min=inicio, fin_min=inicio + 60, hora_inicio=f"{inicio // 60:02d}:00",
                hora_fin=f"{inicio // 60 + 1:02d}:00"))
            inicio += 60
    db.flush()
    return v


def _evento(db, crono, version, tipo, usuario=None, *, minutos=30, **valores) -> CronogramaEvento:
    evento = CronogramaEvento(cronograma_id=crono.id, version_id=version.id if version else None, tipo=tipo,
                              usuario_id=usuario.id if usuario else None,
                              ocurrido_at=AHORA - dt.timedelta(minutes=minutos), **valores)
    db.add(evento)
    db.flush()
    return evento


def _avisos(db, modulo) -> list[dict]:
    db.flush()
    return [a for a in avisos_service.avisos(db, modulo) if a["codigo"] == "cronograma"]


# --- Generar y regenerar ---------------------------------------------------------------


def test_generado_trae_el_plan_completo(db, modulo, turnos, encargado):
    crono = _cronograma(db, modulo)
    v1 = _version(db, crono, turnos, 1, ciclos=2)
    crono.borrador_version_id = v1.id
    evento = _evento(db, crono, v1, TipoEventoCronograma.generado, encargado, detalle={"generacion_id": 7, "version": 1})
    [aviso] = _avisos(db, modulo)
    assert aviso["clave"] == f"cronograma:{modulo.id}:2026-11-09:g7"
    assert aviso["titulo"] == "Plan de riego generado · lunes 09/11" and aviso["icono"] == "📋"
    assert aviso["destino"] == "cronogramas" and aviso["severidad"] == "info"
    assert aviso["ruta"] == f"/cronogramas/{crono.id}"
    detalle = aviso["detalle"]
    assert detalle.startswith(f"Plan del lunes 09/11/2026 · {modulo.nombre}\n")
    assert "Lo generó Ana Campos (encargado) el 08/11/2026 a las 09:30." in detalle
    assert "Versión 1 (del modelo) · estado actual: borrador (sin publicar)" in detalle
    area = {t.codigo: t.area_ha for t in turnos}
    total = sum(20.0 * a for a in area.values())
    assert f"Total: {total:,.0f} m³ · 20.0 m³/ha" in detalle
    te01 = area["TE01"]
    assert f"• TE01 ({te01:,.2f} ha) · 2 ciclo(s) · 06:00–08:00: {20 * te01:,.0f} m³ · 20.0 m³/ha" in detalle
    assert f"   1) 06:00–07:00 · {10 * te01:,.0f} m³ · 10.0 m³/ha" in detalle
    assert detalle.endswith(f"🔗 Ver en la app: http://localhost:5173/cronogramas/{crono.id}") or \
        detalle.endswith(f"/cronogramas/{crono.id}")
    assert "Turnos que cambiaron" not in detalle  # una generación nueva no compara
    assert aviso["resumen"].startswith("lunes 09/11 · versión 1 · ") and aviso["resumen"].endswith("por Ana Campos (encargado)")
    assert aviso["valores"]["ocurrido_at"] == evento.ocurrido_at


def test_regenerado_muestra_lo_que_cambio(db, modulo, turnos, encargado):
    crono = _cronograma(db, modulo)
    _version(db, crono, turnos, 1)
    v2 = _version(db, crono, turnos, 2, OrigenVersion.regenerado, m3ha={"TE01": 30.0})
    _evento(db, crono, v2, TipoEventoCronograma.regenerado, encargado, detalle={"generacion_id": 8, "version": 2})
    [aviso] = _avisos(db, modulo)
    assert aviso["titulo"] == "Plan de riego regenerado · lunes 09/11" and aviso["icono"] == "🔄"
    assert "Lo regeneró Ana Campos" in aviso["detalle"]
    assert "Turnos que cambiaron: TE01" in aviso["detalle"]
    te01 = next(t.area_ha for t in turnos if t.codigo == "TE01")
    assert f"(antes: {20 * te01:,.0f} m³ · 20.0 m³/ha, 1 ciclo(s), 06:00–07:00, +50.0 %)" in aviso["detalle"]
    assert "(antes: " in aviso["detalle"].split("Turnos que cambiaron")[0]  # el total también compara


def test_regenerado_igual_dice_que_no_cambio(db, modulo, turnos, encargado):
    crono = _cronograma(db, modulo)
    _version(db, crono, turnos, 1)
    v2 = _version(db, crono, turnos, 2, OrigenVersion.regenerado)
    _evento(db, crono, v2, TipoEventoCronograma.regenerado, encargado, detalle={"generacion_id": 11})
    [aviso] = _avisos(db, modulo)
    assert "(sin cambios frente a la versión anterior)" in aviso["detalle"]
    assert "Ningún turno cambió." in aviso["detalle"] and "+0.0 %" not in aviso["detalle"]


def test_generacion_de_varios_dias_es_un_solo_aviso(db, modulo, turnos, encargado):
    for i in range(3):
        crono = _cronograma(db, modulo, MANANA + dt.timedelta(days=i))
        v = _version(db, crono, turnos, 1)
        _evento(db, crono, v, TipoEventoCronograma.generado, encargado, detalle={"generacion_id": 9, "version": 1})
    [aviso] = _avisos(db, modulo)
    assert aviso["titulo"] == "Se generaron 3 planes de riego · del 09/11 al 11/11"
    assert aviso["ruta"] == "/cronogramas" and aviso["resumen"].startswith("3 días, del 09/11 al 11/11")
    for dia in ("lunes 09/11", "martes 10/11", "miércoles 11/11"):
        assert f"• {dia} · versión 1 · " in aviso["detalle"]
    assert aviso["detalle"].count("   TE01: ") == 3
    assert "escribe /plan DD/MM al bot" in aviso["detalle"]


# --- Corregir, publicar y otros eventos ---------------------------------------------------


def test_corregido_con_motivo_y_diferencias(db, modulo, turnos, encargado):
    motivo = db.scalars(select(MotivoCorreccion).order_by(MotivoCorreccion.orden)).first()
    crono = _cronograma(db, modulo, estado=EstadoCronograma.publicado)
    v1 = _version(db, crono, turnos, 1)
    v2 = _version(db, crono, turnos, 2, OrigenVersion.correccion, m3ha={"TE02": 15.0}, basada_en_id=v1.id)
    _evento(db, crono, v2, TipoEventoCronograma.corregido, encargado, motivo_codigo=motivo.codigo,
            comentario="llovió en la madrugada")
    [aviso] = _avisos(db, modulo)
    assert aviso["titulo"] == "Plan de riego corregido · lunes 09/11" and aviso["icono"] == "✏️"
    assert f"Motivo: {motivo.nombre} — llovió en la madrugada" in aviso["detalle"]
    assert "Versión 2 (corregida)" in aviso["detalle"] and "Turnos que cambiaron: TE02" in aviso["detalle"]


def test_publicado_y_modificado(db, modulo, turnos, encargado):
    crono = _cronograma(db, modulo, estado=EstadoCronograma.publicado)
    v1 = _version(db, crono, turnos, 1, publicada_at=AHORA - dt.timedelta(hours=3))
    v2 = _version(db, crono, turnos, 2, OrigenVersion.correccion, m3ha={"TE03": 25.0}, basada_en_id=v1.id)
    crono.version_publicada_id = v2.id
    _evento(db, crono, v1, TipoEventoCronograma.publicado, encargado, minutos=180)
    _evento(db, crono, v2, TipoEventoCronograma.modificado, encargado, minutos=10, detalle={"retrospectiva": False})
    publicado, modificado = _avisos(db, modulo)  # en el orden en que pasaron
    assert publicado["titulo"] == "Plan de riego publicado · lunes 09/11"
    assert "El programador ya puede verlo." in publicado["detalle"]
    assert modificado["titulo"] == "Cambios publicados en el plan de riego · lunes 09/11"
    assert "El programador ya ve la nueva versión." in modificado["detalle"]
    assert "Turnos que cambiaron: TE03" in modificado["detalle"]
    assert {publicado["clave"], modificado["clave"]} == {
        f"cronograma:{modulo.id}:2026-11-09:e{e.id}" for e in db.scalars(select(CronogramaEvento))}


@pytest.mark.parametrize(("tipo", "titulo", "severidad", "texto"), [
    (TipoEventoCronograma.correccion_solicitada, "Piden corregir el plan de riego", "media", "Motivo: falta el TE05"),
    (TipoEventoCronograma.correccion_mantenida, "Se mantiene el plan de riego sin cambios", "info",
     "Comentario: falta el TE05"),
    (TipoEventoCronograma.anulado, "Plan de riego anulado", "media", "Motivo: falta el TE05"),
])
def test_otros_eventos(db, modulo, turnos, encargado, tipo, titulo, severidad, texto):
    crono = _cronograma(db, modulo, estado=EstadoCronograma.publicado)
    v1 = _version(db, crono, turnos, 1)
    crono.version_publicada_id = v1.id
    _evento(db, crono, v1, tipo, encargado, comentario="falta el TE05")
    [aviso] = _avisos(db, modulo)
    assert aviso["titulo"] == f"{titulo} · lunes 09/11" and aviso["severidad"] == severidad
    assert texto in aviso["detalle"]
    assert ("   1) 06:00" in aviso["detalle"]) is (tipo != TipoEventoCronograma.anulado)


def test_borrador_descartado_muestra_lo_vigente(db, modulo, turnos, encargado):
    crono = _cronograma(db, modulo, estado=EstadoCronograma.publicado)
    v1 = _version(db, crono, turnos, 1)
    v2 = _version(db, crono, turnos, 2, OrigenVersion.correccion, m3ha={"TE01": 40.0})
    crono.version_publicada_id = v1.id
    _evento(db, crono, v2, TipoEventoCronograma.borrador_descartado, encargado)
    [aviso] = _avisos(db, modulo)
    assert "Se descartó la versión 2; sigue vigente la publicada." in aviso["detalle"]
    assert "Versión 1 (del modelo)" in aviso["detalle"]


def test_no_avisa_vistas_ni_eventos_viejos(db, modulo, turnos, encargado):
    crono = _cronograma(db, modulo)
    v1 = _version(db, crono, turnos, 1)
    _evento(db, crono, v1, TipoEventoCronograma.visto_programador, encargado)
    _evento(db, crono, v1, TipoEventoCronograma.correccion_atendida, encargado)
    _evento(db, crono, v1, TipoEventoCronograma.publicado, encargado, minutos=13 * 60)
    assert _avisos(db, modulo) == []


def test_el_texto_largo_se_recorta_y_conserva_el_enlace(db, modulo, turnos, encargado):
    for i in range(14):
        crono = _cronograma(db, modulo, MANANA + dt.timedelta(days=i))
        _evento(db, crono, _version(db, crono, turnos, 1, ciclos=3), TipoEventoCronograma.generado, encargado,
                detalle={"generacion_id": 10})
    [aviso] = _avisos(db, modulo)
    assert len(aviso["titulo"]) + len(aviso["detalle"]) < 4000
    assert "… (el detalle completo está en la app)\n\n🔗 Ver en la app: " in aviso["detalle"]


# --- API: confirmación, auditoría y /plan --------------------------------------------------


def test_confirmar_un_aviso_de_cronograma(client: TestClient, db, modulo, turnos, token, encargado):
    crono = _cronograma(db, modulo)
    evento = _evento(db, crono, _version(db, crono, turnos, 1), TipoEventoCronograma.publicado, encargado)
    db.commit()
    clave = f"cronograma:{modulo.id}:2026-11-09:e{evento.id}"
    pendientes = client.get(f"{API}/copiloto/avisos", params={"pendientes": True}, headers=agente(token)).json()
    assert [a["clave"] for a in pendientes["avisos"]] == [clave]
    respuesta = client.post(f"{API}/copiloto/avisos/confirmar", json={"claves": [clave]}, headers=agente(token))
    assert respuesta.json() == {"confirmadas": 1, "ya_confirmadas": 0}
    assert client.get(f"{API}/copiloto/avisos", params={"pendientes": True}, headers=agente(token)).json()["avisos"] == []


def test_la_consulta_periodica_de_avisos_no_se_audita(client: TestClient, db, token):
    for _ in range(3):
        assert client.get(f"{API}/copiloto/avisos", params={"pendientes": True}, headers=agente(token)).status_code == 200
    assert client.get(f"{API}/copiloto/resumen", headers=agente(token)).status_code == 200
    rutas = [a.detalle["ruta"] for a in db.scalars(select(Auditoria).where(Auditoria.accion == "consulta_agente"))]
    assert rutas == ["/api/v1/copiloto/resumen"]


@pytest.mark.parametrize(("texto", "esperado"), [
    ("hoy", dt.date(2026, 11, 8)), ("", dt.date(2026, 11, 8)), ("mañana", MANANA), ("MANANA", MANANA),
    ("ayer", dt.date(2026, 11, 7)), ("pasado mañana", dt.date(2026, 11, 10)), ("lunes", MANANA),
    ("domingo", dt.date(2026, 11, 8)), ("miércoles", dt.date(2026, 11, 11)), ("23/11", dt.date(2026, 11, 23)),
    ("5-1", dt.date(2027, 1, 5)), ("23/11/2025", dt.date(2025, 11, 23)), ("23/11/26", dt.date(2026, 11, 23)),
    ("2026-11-23", dt.date(2026, 11, 23)),
])
def test_interpretar_dia(texto, esperado):
    assert avisos_service.interpretar_dia(texto, dt.date(2026, 11, 8)) == esperado


@pytest.mark.parametrize("texto", ["31/02", "el otro día", "13/13/2026", "99"])
def test_dia_que_no_se_entiende(texto):
    with pytest.raises(Exception, match="No entendí la fecha"):
        avisos_service.interpretar_dia(texto, dt.date(2026, 11, 8))


def test_plan_en_texto_por_api(client: TestClient, db, modulo, turnos, token):
    crono = _cronograma(db, modulo)
    crono.borrador_version_id = _version(db, crono, turnos, 1, ciclos=2).id
    db.commit()
    respuesta = client.get(f"{API}/copiloto/plan/texto", params={"dia": "mañana"}, headers=agente(token))
    assert respuesta.status_code == 200, respuesta.text
    datos = respuesta.json()
    assert datos["hay_plan"] is True and datos["fecha"] == "2026-11-09" and datos["cronograma_id"] == crono.id
    assert datos["texto"].startswith(f"📋 Plan de riego del lunes 09/11/2026 · {modulo.nombre}\nVersión 1")
    assert "   2) 07:00–08:00 · " in datos["texto"]
    sin_plan = client.get(f"{API}/copiloto/plan/texto", params={"dia": "15/11"}, headers=agente(token)).json()
    assert sin_plan["hay_plan"] is False and sin_plan["texto"].startswith("No hay plan de riego para el domingo 15/11/2026")
    assert client.get(f"{API}/copiloto/plan/texto", params={"dia": "31/02"}, headers=agente(token)).status_code == 422
    assert client.get(f"{API}/copiloto/plan/texto", params={"dia": "<script>"}, headers=agente(token)).status_code == 422


# --- Contrato con los flujos de n8n ---------------------------------------------------------


@pytest.mark.parametrize("archivo", ("agente_telegram.json", "devlum/agente_telegram.json"))
def test_comando_plan_del_bot_llama_una_ruta_valida(client: TestClient, token, archivo):
    nodos = {n["name"]: n for n in json.loads((FLUJOS / archivo).read_text(encoding="utf-8"))["nodes"]}
    consulta = nodos["Plan en texto"]["parameters"]
    assert consulta["queryParameters"]["parameters"][0]["name"] == "dia"
    assert client.get(_ruta(consulta["url"]), params={"dia": "hoy"}, headers=agente(token)).status_code == 200


def test_flujo_de_avisos_cada_10_minutos_con_chats_de_cronogramas():
    flujo = json.loads((FLUJOS / "avisos.json").read_text(encoding="utf-8"))
    nodos = {n["name"]: n for n in flujo["nodes"]}
    regla = nodos["Cada 10 minutos"]["parameters"]["rule"]["interval"][0]
    assert regla == {"field": "cronExpression", "expression": "*/10 5-22 * * *"}
    campos = {a["name"] for a in nodos["Configuración"]["parameters"]["assignments"]["assignments"]}
    assert {"chat_ids_campo", "chat_ids_sistema", "chat_ids_cronogramas"} <= campos
