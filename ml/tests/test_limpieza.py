import pandas as pd

from riego_ml.dataset.limpieza import limpiar_ciclos, tabla_turno_dia


def _ciclo(fecha, turno, inicio, duracion, m3ha):
    return {
        "Fecha": pd.Timestamp(fecha), "Fundo": "F", "Modulo": "M", "Turno": turno, "Valvula": 1,
        "inicio_min": inicio, "fin_min": inicio + duracion, "hora_inicio": "", "hora_fin": "",
        "fin_dia_siguiente": 0, "duracion_min": duracion, "riego_m3": m3ha * 10,
        "riego_m3ha": m3ha, "area_ha": 10.0,
    }


def test_descarta_fallidos_y_renumera_por_hora():
    riego = pd.DataFrame([
        _ciclo("2024-01-01", "TE01", 900, 60, 20),
        _ciclo("2024-01-01", "TE01", 300, 60, 20),   # más temprano -> ciclo 1
        _ciclo("2024-01-01", "TE01", 600, 0.2, 0),   # apertura fallida
        _ciclo("2024-01-01", "TE02", 100, 50, 15),
    ])
    ciclos, descartados, diag = limpiar_ciclos(riego, min_duracion_min=5, min_riego_m3ha=2)
    assert len(descartados) == 1
    te01 = ciclos[ciclos["Turno"] == "TE01"].sort_values("Ciclo")
    assert te01["inicio_min"].tolist() == [300, 900]
    assert te01["n_ciclos"].tolist() == [2, 2]


def test_marca_solapados_y_dia_incompleto():
    riego = pd.DataFrame([
        _ciclo("2024-01-01", "TE01", 100, 120, 20),
        _ciclo("2024-01-01", "TE01", 200, 30, 10),   # empieza antes de que termine el anterior
        _ciclo("2024-01-01", "TE02", 100, 30, 10),
        _ciclo("2024-01-02", "TE01", 100, 30, 10),   # ese día falta TE02
    ])
    ciclos, _, _ = limpiar_ciclos(riego, 5, 2)
    assert ciclos["solapado"].sum() == 1
    td = tabla_turno_dia(ciclos)
    assert td.set_index(["Fecha", "Turno"]).loc[(pd.Timestamp("2024-01-02"), "TE01"), "dia_incompleto"] == 1
