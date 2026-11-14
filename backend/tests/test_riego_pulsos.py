"""Riego por pulsos: paridad con la planilla, parámetros por módulo y generación de cronogramas."""
from __future__ import annotations

import dataclasses
import datetime as dt
from types import SimpleNamespace

import pandas as pd
import pytest
import time_machine
from sqlalchemy import select

from app.core.tiempo import hoy_lima
from app.ml.generador import PrediccionDia
from app.ml.historial_bd import construir_historial
from app.models import Auditoria, ParametrosPulsos, PrediccionEntrada
from app.repositories import cronogramas as repo
from app.services import calculo_pulsos as cp
from app.services import cronograma_service
from app.services import parametros_pulsos_service as servicio
from tests.conftest import API

TURNOS = ["TE01", "TE02", "TE03", "TE04", "TE05"]
PARAMETROS = servicio.a_parametros(servicio.POR_DEFECTO)


# --- Paridad con la planilla (hoja «PULSOS PALTO», ETo 5 mm, crecimiento de fruta) -----------

def test_derivados_iguales_a_la_planilla():
    d = cp.derivados(PARAMETROS, 5)
    assert d.volumen_explorado_m3ha == pytest.approx(1666.6667, abs=1e-3)      # K8
    assert d.agua_disponible_m3ha == pytest.approx(166.6667, abs=1e-3)         # K12
    assert d.capacidad_riego_m3hah == pytest.approx(21.3333, abs=1e-3)         # S14
    assert d.agotamiento_max_bloque == pytest.approx(0.05984, abs=1e-5)        # S62
    assert d.agotamiento_operativo == 0.05                                     # G19
    assert d.volumen_pulso_m3ha == pytest.approx(9.8039, abs=1e-3)             # J19
    assert d.minutos_pulso == pytest.approx(27.5735, abs=1e-3)                 # L19
    assert d.plantas_ha == pytest.approx(833.33, abs=0.01)                     # S12
    assert d.amortiguacion_m3ha == pytest.approx(33.3333, abs=1e-3)            # K15


def test_eto_5_da_los_pulsos_de_la_planilla():
    """ETo 5 × Kc 1 = 50 m³/ha netos → 58,82 brutos: la planilla da 1 pulso por bloque (J23:J38),
    curva 2 por umbral que no converge → curva 3, 03:00–21:00, 137,9 min por bloque."""
    p = dataclasses.replace(PARAMETROS, ajustar_pulso_al_total=False)
    plan = cp.calcular({t: 50 / 0.85 for t in TURNOS}, {t: 13.0 for t in TURNOS}, p)
    assert (plan.curva_propuesta, plan.curva) == ("2", "3")
    assert plan.etr_equivalente_mm == pytest.approx(5.0)
    te01 = plan.turnos["TE01"]
    assert [round(x, 2) for x in te01.teoricos] == [0.84, 1.08, 1.08, 1.08, 1.08, 0.84]  # I23..I38
    assert te01.pulsos_por_bloque == [1, 1, 1, 1, 1, 1]
    assert [round(m, 1) for m in plan.minutos_riego_bloque] == [137.9] * 6                # L23..L38
    assert plan.converge and plan.avisos == []
    detalle = cp.detalle(plan, p)
    assert detalle["ventana"] == ["03:00", "21:00"]
    assert "no converge, se usa la curva 3" in detalle["motivo"]


def test_m3ha_del_modelo_horario_y_total_exacto():
    totales = {"TE01": 51.99, "TE02": 51.47, "TE03": 51.82, "TE04": 51.62, "TE05": 53.92}
    plan = cp.calcular(totales, {t: 13.0 for t in TURNOS}, PARAMETROS)
    assert plan.curva == "3"
    for turno, total in totales.items():
        t = plan.turnos[turno]
        assert t.pulsos_por_bloque == [1, 1, 1, 1, 1, 0]
        assert sum(c.riego_m3ha for c in t.ciclos) == pytest.approx(total, abs=0.03)
        for c in t.ciclos:  # duración = m³/ha ÷ capacidad de riego
            assert c.duracion_min == pytest.approx(c.riego_m3ha * 60 / 21.3333, abs=0.06)
    assert [(c.hora_inicio, c.hora_fin) for c in plan.turnos["TE01"].ciclos] == [
        ("03:00", "03:29"), ("05:27", "05:56"), ("07:53", "08:22"), ("10:20", "10:49"), ("12:46", "13:16")]
    assert [(c.hora_inicio, c.hora_fin) for c in plan.turnos["TE02"].ciclos][:2] == [
        ("03:29", "03:58"), ("05:56", "06:25")]
    assert cp.detalle(plan, PARAMETROS)["horario"] == ["03:00", "15:13"]
    # En fila por vueltas: ciclo 1 de TE01…TE05, luego los ciclos 2, …; cada uno empieza cuando
    # termina el anterior (sin solaparse ni dejar huecos).
    fila = sorted((c.inicio_min, c.fin_min, c.ciclo, turno) for turno, t in plan.turnos.items() for c in t.ciclos)
    assert [(ciclo, turno) for _, _, ciclo, turno in fila] == [(k, t) for k in range(1, 6) for t in TURNOS]
    assert fila[0][0] == 180
    assert all(a[1] == b[0] for a, b in zip(fila, fila[1:]))


def test_horario_en_fila_con_los_m3ha_del_modelo_del_13_11():
    """El ejemplo revisado con el usuario (modelo 2026-11-07_1115, cronograma del 13/11)."""
    totales = {"TE01": 53.29, "TE02": 53.79, "TE03": 49.57, "TE04": 50.43, "TE05": 47.91}
    areas = {"TE01": 13.019, "TE02": 12.649, "TE03": 12.423, "TE04": 12.459, "TE05": 12.2792}
    plan = cp.calcular(totales, areas, PARAMETROS)
    assert plan.curva == "3" and plan.converge
    assert [t.n_ciclos for t in plan.turnos.values()] == [5] * 5
    primera = [(c.hora_inicio, c.hora_fin) for t in plan.turnos.values() for c in t.ciclos[:1]]
    assert primera == [("03:00", "03:30"), ("03:30", "04:00"), ("04:00", "04:28"), ("04:28", "04:57"),
                       ("04:57", "05:24")]
    assert plan.turnos["TE01"].ciclos[1].hora_inicio == "05:24"
    assert plan.turnos["TE05"].ciclos[-1].hora_fin == "14:58"
    c = plan.turnos["TE01"].ciclos[0]
    assert (c.riego_m3ha, c.riego_m3, c.duracion_min) == (10.66, 138.8, 30.0)


def test_eto_baja_usa_curva_1_y_redondeo_minimo_un_pulso():
    plan = cp.calcular({"TE01": 20.0, "TE02": 4.0}, {"TE01": 10.0, "TE02": 10.0}, PARAMETROS)
    assert plan.curva == "1" and plan.curva_propuesta == "1"
    assert plan.turnos["TE01"].n_ciclos == 2
    assert plan.turnos["TE02"].n_ciclos == 1  # 4 m³/ha < medio pulso: igual se programa 1
    # Con la curva 1 la fila empieza a las 06:00: TE01 ciclo 1, TE02 ciclo 1, TE01 ciclo 2.
    assert [(c.hora_inicio, c.hora_fin) for c in plan.turnos["TE01"].ciclos] == [("06:00", "06:28"), ("06:39", "07:07")]
    assert [(c.hora_inicio, c.hora_fin) for c in plan.turnos["TE02"].ciclos] == [("06:28", "06:39")]


def test_modo_forzado_y_aviso_si_no_converge():
    p = dataclasses.replace(PARAMETROS, modo_ventana="curva_1")
    plan = cp.calcular({t: 80.0 for t in TURNOS}, {t: 13.0 for t in TURNOS}, p)
    assert plan.curva == "1" and not plan.converge
    assert any("No converge" in a for a in plan.avisos)
    assert "fijada" in plan.motivo


def test_alternativas_conservan_el_total():
    totales = {t: 52.0 for t in TURNOS}
    areas = {t: 13.0 for t in TURNOS}
    plan = cp.calcular(totales, areas, PARAMETROS)
    alternativas = cp.alternativas(plan, totales, areas, PARAMETROS)
    assert sorted(alternativas["TE01"]) == list(range(1, cp.MAX_PULSOS_TURNO + 1))
    for n, ciclos in alternativas["TE03"].items():
        assert len(ciclos) == n
        assert sum(c["riego_m3ha"] for c in ciclos) == pytest.approx(52.0, abs=0.01 * n + 0.01)


# --- Parámetros por API ---------------------------------------------------------------------

def _entrada(**cambios):
    datos = {k: v for k, v in servicio.POR_DEFECTO.items()}
    datos.update(cambios)
    return datos


def test_parametros_lectura_para_todos_y_edicion_auditada(client, auth, db):
    r = client.get(f"{API}/modulos/1/parametros-pulsos", headers=auth("programador"))
    assert r.status_code == 200, r.text
    cuerpo = r.json()
    assert cuerpo["guardado"] and cuerpo["activo"] and cuerpo["derivados"]["turnos"] == 5
    assert cuerpo["derivados"]["volumen_pulso_m3ha"] == pytest.approx(9.8039, abs=1e-3)

    r = client.put(f"{API}/modulos/1/parametros-pulsos", headers=auth("programador", "prog2"),
                   json=_entrada(fase_fenologica="Vegetativo"))
    assert r.status_code == 403

    r = client.put(f"{API}/modulos/1/parametros-pulsos", headers=auth("encargado"),
                   json=_entrada(fase_fenologica="Vegetativo"))
    assert r.status_code == 200, r.text
    d = r.json()["derivados"]
    # Vegetativo: δ 10 % no cabe en 3 h con 5 turnos → se usa el máximo del bloque (5,98 %).
    assert d["agotamiento_operativo"] == pytest.approx(0.05984, abs=1e-5)
    assert any("no cabe" in a for a in r.json()["avisos"])
    assert r.json()["actualizado_por"]
    fila = db.scalar(select(Auditoria).where(Auditoria.accion == "actualizar_parametros_pulsos"))
    assert fila is not None and "fase_fenologica" in fila.detalle["cambios"]


@pytest.mark.parametrize("cambios, mensaje", [
    ({"punto_marchitez": 0.2}, "marchitez"),
    ({"umbral_etr_1": 6.0}, "umbral"),
    ({"fase_fenologica": "Inexistente"}, "fase"),
    ({"curvas": {**servicio.POR_DEFECTO["curvas"], "1": {"6": 50, "7": 40}}}, "suma 90"),
    ({"curvas": {**servicio.POR_DEFECTO["curvas"], "2": {"23": 100}}}, "03:00 a 20:00"),
    ({"curvas": {"1": servicio.POR_DEFECTO["curvas"]["1"]}}, "curvas 1, 2 y 3"),
])
def test_parametros_invalidos(client, auth, cambios, mensaje):
    r = client.put(f"{API}/modulos/1/parametros-pulsos", headers=auth("admin"), json=_entrada(**cambios))
    assert r.status_code in (400, 422), r.text
    assert mensaje in r.text


def test_parametros_modulo_inexistente(client, auth):
    assert client.get(f"{API}/modulos/999999/parametros-pulsos", headers=auth()).status_code == 404


# --- Generación de cronogramas ----------------------------------------------------------------

@pytest.fixture
def reloj():
    with time_machine.travel(dt.datetime(2026, 11, 11, 15, tzinfo=dt.UTC), tick=False):
        yield


def _modelo_falso(monkeypatch, fecha):
    """Sustituye solo las fronteras del modelo: 3 ciclos de ~17 m³/ha por turno."""
    monkeypatch.setattr(repo, "dias_con_riego_antes", lambda *a: 45)
    monkeypatch.setattr(cronograma_service, "cargar_modelo", lambda: SimpleNamespace(plan=object(), version="prueba"))
    monkeypatch.setattr(cronograma_service, "registrar_version", lambda *a: None)
    filas = []
    for i, turno in enumerate(TURNOS):
        for k, (inicio, m3ha) in enumerate(((400., 15.28), (683., 18.9), (969., 17.81)), start=1):
            dur = round(m3ha * 2.5, 1)
            filas.append({"Turno": turno, "n_ciclos": 3, "Ciclo": k, "riego_m3ha": m3ha, "riego_m3": round(m3ha * 13, 1),
                          "duracion_min": dur, "inicio_min": inicio + 20 * i, "fin_min": inicio + 20 * i + dur,
                          "hora_inicio": cp.hhmm(inicio + 20 * i), "hora_fin": cp.hhmm(inicio + 20 * i + dur),
                          "fin_dia_siguiente": 0})
    prediccion = PrediccionDia(fecha, pd.DataFrame(filas), {t: {} for t in TURNOS}, {},
                               alternativas={t: {} for t in TURNOS}, factor={t: 2.5 for t in TURNOS})
    monkeypatch.setattr(cronograma_service.generador, "predecir_dia", lambda *a: prediccion)
    monkeypatch.setattr(cronograma_service.generador, "agregar", lambda historial, pred: historial)


def _generar(client, cabeceras, fecha):
    r = client.post(f"{API}/cronogramas/generar", headers=cabeceras,
                    json={"modulo_id": 1, "fecha_inicio": str(fecha), "dias": 1})
    assert r.status_code == 200, r.text
    return r.json()["dias_resultado"][0]["cronograma_id"]


def test_generar_con_pulsos_guarda_pulsos_calculo_y_plan_del_modelo(client, auth, db, reloj, monkeypatch):
    cabeceras = auth("encargado")
    fecha = hoy_lima() + dt.timedelta(days=1)
    _modelo_falso(monkeypatch, fecha)
    crono_id = _generar(client, cabeceras, fecha)

    r = client.get(f"{API}/cronogramas/{crono_id}", headers=cabeceras)
    version = r.json()["version"]
    calculo = version["calculo_pulsos"]
    assert calculo["metodo"] == "pulsos" and calculo["curva"] == "3" and calculo["converge"]
    for t in version["turnos"]:
        assert t["n_ciclos"] == 5 and len(t["ciclos"]) == 5
        assert t["total_m3ha"] == pytest.approx(51.99, abs=0.03)  # = total del modelo
        assert t["factor_min_por_m3ha"] == pytest.approx(60 / 21.3333, abs=1e-3)
        assert t["ciclos"][0]["m3ha_p10"] is None
    te01 = next(t for t in version["turnos"] if t["turno_codigo"] == "TE01")
    assert [c["hora_inicio"] for c in te01["ciclos"]] == ["03:00", "05:26", "07:52", "10:18", "12:44"]
    assert calculo["horario"] == ["03:00", "15:10"]

    entradas = db.scalars(select(PrediccionEntrada)).all()
    assert len(entradas) == 5 and all(len(e.plan_modelo) == 3 for e in entradas)
    alternativas = client.get(f"{API}/cronogramas/{crono_id}/alternativas", headers=cabeceras).json()
    assert sorted(int(n) for n in alternativas[str(te01["turno_id"])]) == list(range(1, 13))

    # Editar a 6 ciclos (más que el máximo del modelo) se puede.
    seis = alternativas[str(te01["turno_id"])]["6"]
    r = client.post(f"{API}/cronogramas/{crono_id}/recalcular", headers=cabeceras, json={
        "basada_en_id": version["id"],
        "turnos": [{"turno_id": te01["turno_id"], "n_ciclos": 6, "ciclos": [
            {"ciclo": c["ciclo"], "riego_m3ha": c["riego_m3ha"], "inicio_min": c["inicio_min"],
             "duracion_min": c["duracion_min"], "duracion_manual": False} for c in seis]}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["calculo_pulsos"]["curva"] == "3"

    # El historial del día siguiente usa lo que predijo el modelo, no los pulsos.
    historial = construir_historial(db, 1, hasta=fecha + dt.timedelta(days=1)).historial
    del_dia = historial.ciclos[historial.ciclos["Fecha"] == pd.Timestamp(fecha)]
    assert len(del_dia) == 15 and set(del_dia.groupby("Turno").size()) == {3}


def test_generar_sin_pulsos_guarda_el_plan_del_modelo(client, auth, db, reloj, monkeypatch):
    db.query(ParametrosPulsos).filter(ParametrosPulsos.modulo_id == 1).update({"activo": False})
    db.commit()
    cabeceras = auth("encargado")
    fecha = hoy_lima() + dt.timedelta(days=1)
    _modelo_falso(monkeypatch, fecha)
    crono_id = _generar(client, cabeceras, fecha)
    version = client.get(f"{API}/cronogramas/{crono_id}", headers=cabeceras).json()["version"]
    assert version["calculo_pulsos"] is None
    assert {t["n_ciclos"] for t in version["turnos"]} == {3}
    assert db.scalars(select(PrediccionEntrada.plan_modelo)).all() == [None] * 5
