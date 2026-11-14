"""Pruebas del experimento "total m³/ha por turno-día" (ml/experimentos/exp_total_turno.py)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experimentos"))

import exp_total_turno as ett  # noqa: E402
from riego_ml.dataset.features import construir_features_turno  # noqa: E402
from riego_ml.modeling.planificador import PlanRiego  # noqa: E402
from riego_ml.modeling.split import cortes_temporales  # noqa: E402

CLAVES = ["Fecha", "Fundo", "Modulo", "Turno"]


def _turno_dia(fechas, turnos=("TE01", "TE02")):
    filas = [{"Fecha": f, "Fundo": "F", "Modulo": "M", "Turno": t} for f in fechas for t in turnos]
    td = pd.DataFrame(filas)
    td["riego_total_m3ha"] = np.arange(len(td), dtype=float) + 10
    td["n_ciclos"] = 2
    td["duracion_total_min"] = 60.0
    td["inicio_primer_min"] = 300.0
    td["fin_ultimo_min"] = 360.0
    td["area_ha"] = 5.0
    td["dia_incompleto"] = 0
    return td


def _ambiente(fechas):
    amb = pd.DataFrame({"Fundo": "F", "Fecha": fechas})
    for c in ["T_media", "T_max", "T_min", "HR_media", "HR_min", "ETo_mm", "DPV_media", "DPV_max",
              "Viento_media", "Lluvia_mm", "Rad_max", "Rad_media", "mds_contraccion_um",
              "crecimiento_tronco_um", "estres_planta_ps"]:
        amb[c] = np.arange(len(fechas)) * 1.0
    for c in ["hum_15cm", "hum_30cm", "hum_45cm", "hum_60cm", "hum_75cm", "hum_90cm",
              "hum_zona_radicular", "hum_linea_estres"]:
        amb[f"{c}_cierre"] = np.arange(len(fechas)) * 1.0
    return amb


def test_grilla_agrega_dias_sin_riego_y_deja_fuera_huecos_largos():
    todas = pd.date_range("2024-01-01", "2024-01-31")
    sin_riego = {pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-06")}
    hueco = set(pd.date_range("2024-01-15", "2024-01-24"))  # 10 días
    fechas = [f for f in todas if f not in sin_riego | hueco]
    td = _turno_dia(fechas)
    # Un día incompleto: falta TE02 el 2024-01-10 (no se agrega como 0)
    td = td[~((td["Fecha"] == "2024-01-10") & (td["Turno"] == "TE02"))].copy()
    td.loc[td["Fecha"] == "2024-01-10", "dia_incompleto"] = 1

    grilla, huecos = ett.armar_grilla(td, max_dias_sin_riego=6)

    assert not grilla.duplicated(CLAVES).any()
    ceros = grilla[grilla["sin_riego"] == 1]
    assert set(ceros["Fecha"]) == sin_riego
    assert len(ceros) == 4 and (ceros["riego_total_m3ha"] == 0).all() and (ceros["dia_incompleto"] == 0).all()
    assert not grilla["Fecha"].isin(hueco).any()
    assert len(grilla[grilla["Fecha"] == "2024-01-10"]) == 1
    assert grilla.loc[grilla["Fecha"] == "2024-01-10", "dia_incompleto"].eq(1).all()
    assert set(huecos["tratamiento"]) == {"sin_riego", "hueco_de_datos"}


def test_referencias_usan_solo_dias_anteriores():
    fechas = pd.date_range("2024-01-01", periods=10)
    td = _turno_dia(fechas, turnos=("TE01",))
    grilla, _ = ett.armar_grilla(td, 6)
    ref = ett.referencias(grilla).set_index("Fecha")
    assert np.isnan(ref.loc["2024-01-01", "ref_ayer"])
    assert ref.loc["2024-01-06", "ref_ayer"] == td["riego_total_m3ha"].iloc[4]
    assert ref.loc["2024-01-06", "ref_media7"] == pytest.approx(td["riego_total_m3ha"].iloc[:5].mean())


def test_persistencia_devuelve_el_dia_anterior_con_respaldo():
    filas = pd.DataFrame({"Turno": ["TE01", "TE01", "TE02"], "ref_ayer": [7.0, np.nan, np.nan],
                          "ref_media7": [9.0, 8.0, np.nan]})
    pred = ett.predecir_referencia("persistencia", filas, {"TE01": 1.0, "TE02": 2.0})
    assert pred.tolist() == [7.0, 8.0, 2.0]
    pred7 = ett.predecir_referencia("media_7d", filas, {"TE01": 1.0, "TE02": 2.0})
    assert pred7.tolist() == [9.0, 8.0, 2.0]


def test_features_del_dia_no_cambian_si_cambia_el_riego_de_ese_dia_o_futuro():
    fechas = pd.date_range("2024-01-01", periods=12)
    td = _turno_dia(fechas)
    amb = _ambiente(fechas)
    tabla, _ = ett.construir_tabla(td, amb, False, 6)
    dia = pd.Timestamp("2024-01-08")
    modificado = td.copy()
    modificado.loc[modificado["Fecha"] >= dia, ["riego_total_m3ha", "n_ciclos"]] = [999.0, 5]
    amb_mod = amb.copy()
    amb_mod.loc[amb_mod["Fecha"] >= dia, "ETo_mm"] = 999.0
    tabla_mod, _ = ett.construir_tabla(modificado, amb_mod, False, 6)
    cols = [c for c in tabla.columns if c not in ("riego_total_m3ha", "n_ciclos")]
    a = tabla[tabla["Fecha"] == dia][cols].reset_index(drop=True)
    b = tabla_mod[tabla_mod["Fecha"] == dia][cols].reset_index(drop=True)
    pd.testing.assert_frame_equal(a, b)


def test_features_de_la_grilla_iguales_a_las_del_pipeline():
    fechas = [f for f in pd.date_range("2024-01-01", periods=12) if f != pd.Timestamp("2024-01-05")]
    td = _turno_dia(fechas)
    amb = _ambiente(pd.date_range("2024-01-01", periods=12))
    feats = construir_features_turno(td[CLAVES], td, amb)
    td_feats = td.merge(feats, on=CLAVES)
    tabla, _ = ett.construir_tabla(td, amb, False, 6)
    columnas = [c for c in feats.columns if c not in CLAVES]
    assert ett.diferencia_con_paso2(tabla, td_feats, columnas) == 0.0
    assert (tabla["sin_riego"] == 1).sum() == 2


class _Fijo:
    def __init__(self, valor):
        self.valor = valor

    def predict(self, X):
        return np.full(len(X), self.valor)


def test_total_del_plan_actual_es_la_suma_de_sus_ciclos():
    fechas = pd.date_range("2024-01-01", periods=3)
    td = _turno_dia(fechas)
    plan = PlanRiego(
        modelos={"n_ciclos": _Fijo(3), "riego_m3ha": _Fijo(12.5), "inicio_min": _Fijo(300.0)},
        features={"n_ciclos": ["Turno"], "riego_m3ha": ["Turno"], "inicio_min": ["Turno"]},
        max_ciclos=5, min_por_m3ha={"TE01": 2.0, "TE02": 2.0}, area_ha={"TE01": 5.0, "TE02": 5.0},
        rango_m3ha=(0.0, 100.0),
    )
    ciclos = td[CLAVES].assign(Ciclo=1, riego_m3ha=10.0, inicio_min=300.0, duracion_min=20.0)
    filas = td[td["Fecha"] == fechas[-1]].reset_index(drop=True)
    total = ett.total_plan(plan, filas, ciclos)
    assert total.tolist() == [37.5, 37.5]


def test_por_defecto_y_calculo_de_pulsos_del_backend():
    cp = ett.cargar_calculo_pulsos()
    valores = ett.leer_por_defecto()
    assert valores["eficiencia_aplicacion"] == 0.85
    assert valores["curvas"]["3"]["10"] == 6
    p = ett.a_parametros(cp, valores)
    plan = cp.calcular({"TE01": 40.0, "TE02": 0.0, "TE03": 30.0}, {"TE01": 5, "TE02": 5, "TE03": 5}, p)
    assert plan.turnos["TE02"].n_ciclos == 0
    assert plan.turnos["TE01"].n_ciclos >= 1
    filas = pd.DataFrame({"Fecha": pd.Timestamp("2024-01-01"), "Fundo": "F", "Modulo": "M",
                          "Turno": ["TE01", "TE02", "TE03"], "real": [40.0, 0.0, 30.0], "otro": [40.0, 10.0, 30.0]})
    por_fuente = {f: ett.pulsos_por_dia(cp, p, filas, f, {}) for f in ("real", "otro")}
    resumen, detalle = ett.comparar_pulsos(por_fuente)
    r = resumen.set_index("fuente")
    assert r.loc["real", "pct_n_pulsos_distinto"] == 0
    assert r.loc["otro", "pct_n_pulsos_distinto"] == pytest.approx(100 / 3)
    assert len(detalle) == 3


def test_split_no_mezcla_test_con_train_ni_validacion():
    fechas = pd.Series(pd.date_range("2022-01-01", periods=400))
    cortes = cortes_temporales(fechas, test=0.2, validacion=0.15, gap_dias=7)
    conjunto = cortes.asignar(fechas)
    assert fechas[conjunto == "train"].max() < fechas[conjunto == "validacion"].min() - pd.Timedelta(days=6)
    assert fechas[conjunto == "validacion"].max() < fechas[conjunto == "test"].min() - pd.Timedelta(days=6)


def test_variantes_por_grupo():
    features = ["Turno", "mes", "ETo_mm_d1", "d_hum_45cm_24h", "mds_media3", "prev_riego_total_m3ha",
                "balance_hidrico_7d"]
    v = ett.variantes_features(features, {"riego": ["calendario", "riego"],
                                          "completo": ["calendario", "riego", "clima", "suelo", "planta"]})
    assert v["riego"] == ["Turno", "mes", "prev_riego_total_m3ha"]
    assert v["completo"] == features
