import pandas as pd

from riego_ml.modeling.planificador import PlanRiego, plan_ancho
from riego_ml.modeling.split import cortes_temporales


def _plan(pausa=0.0):
    return PlanRiego(None, None, None, [], [], 5, {"TE01": 3.0}, {"TE01": 13.0}, (2.0, 100.0), pausa_min=pausa)


def test_horario_sin_solapamientos_y_ordenado():
    plan = pd.DataFrame({
        "Fecha": pd.Timestamp("2024-01-01"), "Fundo": "F", "Modulo": "M", "Turno": "TE01",
        "n_ciclos": 2, "Ciclo": [1, 2], "riego_m3ha": [20.0, 10.0],
        "inicio_min": [400.0, 350.0], "duracion_min": [60.0, 30.0],
    })
    horario = _plan(pausa=10).armar_horario(plan)
    assert horario["inicio_min"].tolist() == [350.0, 400.0]
    plan.loc[1, "inicio_min"] = 410.0
    horario = _plan(pausa=10).armar_horario(plan)
    assert horario.loc[1, "inicio_min"] >= horario.loc[0, "fin_min"] + 10
    ancho = plan_ancho(horario, 5)
    assert ancho.loc[0, "n_ciclos"] == 2 and ancho.loc[0, "ciclo1_hora_inicio"] == "06:40"


def test_split_temporal_con_gap():
    fechas = pd.Series(pd.date_range("2022-01-01", periods=400, freq="D"))
    cortes = cortes_temporales(fechas, test=0.2, validacion=0.15, gap_dias=7)
    conjuntos = cortes.asignar(fechas)
    assert (fechas[conjuntos == "train"].max() + pd.Timedelta(days=7)) < fechas[conjuntos == "validacion"].min()
    assert (fechas[conjuntos == "validacion"].max() + pd.Timedelta(days=7)) < fechas[conjuntos == "test"].min()
