import numpy as np
import pandas as pd

from riego_ml.modeling.planificador import PlanRiego
from riego_ml.modeling.total_turno import PlanTotalTurno, escalar_al_total, referencias_total

CLAVE = {"Fundo": "F", "Modulo": "M"}


class _Constante:
    def __init__(self, valor):
        self.valor = valor

    def predict(self, X):
        return np.full(len(X), self.valor, dtype=float)


def _ciclos_hist(dias=5, n=2, m3ha=25.0):
    filas = []
    for fecha in pd.date_range("2026-11-01", periods=dias):
        for k in range(1, n + 1):
            filas.append({"Fecha": fecha, **CLAVE, "Turno": "TE01", "Ciclo": k, "n_ciclos": n,
                          "riego_m3ha": m3ha, "riego_m3": m3ha * 13, "area_ha": 13.0,
                          "duracion_min": m3ha * 3, "inicio_min": 180.0 + 200 * k, "fin_min": 180.0 + 200 * k + m3ha * 3})
    return pd.DataFrame(filas)


def _plan_base(n=4, m3ha=25.0):
    return PlanRiego(
        modelos={"n_ciclos": _Constante(n), "riego_m3ha": _Constante(m3ha), "inicio_min": _Constante(180.0)},
        features={"n_ciclos": [], "riego_m3ha": [], "inicio_min": []}, max_ciclos=12,
        min_por_m3ha={"TE01": 3.0}, area_ha={"TE01": 13.0}, rango_m3ha=(2.0, 100.0),
    )


def test_referencias_solo_dias_anteriores_y_faltante_no_es_cero():
    td = pd.DataFrame({"Fecha": pd.to_datetime(["2026-11-01", "2026-11-02", "2026-11-04"]), **CLAVE,
                       "Turno": "TE01", "riego_total_m3ha": [10.0, 20.0, 40.0]})
    refs = referencias_total(td, [pd.Timestamp("2026-11-05")]).set_index("Fecha")
    assert np.isnan(refs.loc["2026-11-01", "ref_ayer"])
    assert refs.loc["2026-11-03", "ref_ayer"] == 20.0
    assert np.isnan(refs.loc["2026-11-04", "ref_ayer"])  # el 03 no tiene registro
    assert refs.loc["2026-11-05", "ref_ayer"] == 40.0
    assert refs.loc["2026-11-05", "ref_mediana7"] == 20.0


def test_escalar_conserva_reparto_y_suma_el_total():
    ciclos = pd.DataFrame({"Fecha": pd.Timestamp("2026-11-21"), **CLAVE, "Turno": ["TE01"] * 2 + ["TE02"] * 2,
                           "riego_m3ha": [20.0, 30.0, 10.0, 10.0]})
    totales = pd.DataFrame({"Fecha": pd.Timestamp("2026-11-21"), **CLAVE, "Turno": ["TE01"], "total_m3ha": [25.0]})
    out = escalar_al_total(ciclos, totales)
    assert out["riego_m3ha"].tolist() == [10.0, 15.0, 10.0, 10.0]  # TE02 sin total: no se toca


def test_plan_total_turno_es_plan_riego_y_suma_el_total_del_modelo():
    base = _plan_base(n=4, m3ha=25.0)  # el plan base daría 4 × 25 = 100 m³/ha
    plan = PlanTotalTurno.desde_plan(base, _Constante(50.0), ["ref_media7"])
    assert isinstance(plan, PlanRiego) and plan.max_ciclos == 12
    features = pd.DataFrame({"Fecha": [pd.Timestamp("2026-11-06")], **CLAVE, "Turno": ["TE01"]})
    salida = plan.predecir(features, _ciclos_hist())
    assert len(salida) == 4
    assert np.isclose(salida["riego_m3ha"].sum(), 50.0)
    assert np.allclose(salida["duracion_min"], salida["riego_m3ha"] * 3.0, atol=0.1)
    assert (salida["inicio_min"].iloc[1:].to_numpy() >= salida["fin_min"].iloc[:-1].to_numpy()).all()
    assert np.isclose(salida["riego_m3"].sum(), 50.0 * 13.0)
