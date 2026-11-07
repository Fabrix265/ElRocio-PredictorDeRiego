import numpy as np
import pandas as pd

from riego_ml.dataset.features import construir_features_turno


def _datos():
    fechas = pd.date_range("2024-01-01", periods=10, freq="D")
    turno_dia = pd.DataFrame({
        "Fecha": fechas, "Fundo": "F", "Modulo": "M", "Turno": "TE01",
        "n_ciclos": np.arange(10) % 3 + 1, "riego_total_m3ha": np.arange(10) * 1.0,
        "duracion_total_min": 60.0, "inicio_primer_min": 300.0, "fin_ultimo_min": 360.0,
    })
    ambiente = pd.DataFrame({"Fundo": "F", "Fecha": fechas})
    for c in ["T_media", "T_max", "T_min", "HR_media", "HR_min", "ETo_mm", "DPV_media", "DPV_max",
              "Viento_media", "Lluvia_mm", "Rad_max", "Rad_media", "mds_contraccion_um",
              "crecimiento_tronco_um", "estres_planta_ps"]:
        ambiente[c] = np.arange(10) * 1.0
    for c in ["hum_15cm", "hum_30cm", "hum_45cm", "hum_60cm", "hum_75cm", "hum_90cm",
              "hum_zona_radicular", "hum_linea_estres"]:
        ambiente[f"{c}_cierre"] = np.arange(10) * 1.0
    return turno_dia, ambiente


def test_features_del_dia_D_solo_usan_hasta_D_menos_1():
    turno_dia, ambiente = _datos()
    f = construir_features_turno(turno_dia[["Fecha", "Fundo", "Modulo", "Turno"]], turno_dia, ambiente)
    dia = f[f["Fecha"] == "2024-01-06"].iloc[0]   # índice 5
    assert dia["ETo_mm_d1"] == 4.0
    assert dia["hum_45cm_cierre_d1"] == 4.0
    assert dia["prev_riego_total_m3ha"] == 4.0
    assert dia["prev_n_ciclos"] == turno_dia["n_ciclos"].iloc[4]
    assert dia["ETo_media3"] == np.mean([2.0, 3.0, 4.0])


def test_fecha_futura_sin_historial_del_dia():
    turno_dia, ambiente = _datos()
    claves = pd.DataFrame({"Fecha": [pd.Timestamp("2024-01-11")], "Fundo": "F", "Modulo": "M", "Turno": "TE01"})
    f = construir_features_turno(claves, turno_dia, ambiente).iloc[0]
    assert f["prev_riego_total_m3ha"] == 9.0
    assert f["ETo_mm_d1"] == 9.0


def test_rotacion_y_estabilidad_usan_el_dia_anterior():
    turno_dia, ambiente = _datos()
    otro = turno_dia.assign(Turno="TE02", inicio_primer_min=500.0)   # TE02 arranca después que TE01
    td = pd.concat([turno_dia, otro], ignore_index=True)
    f = construir_features_turno(td[["Fecha", "Fundo", "Modulo", "Turno"]], td, ambiente)
    dia = f[(f["Fecha"] == "2024-01-06") & (f["Turno"] == "TE02")].iloc[0]
    assert dia["orden_arranque_d1"] == 2
    assert dia["desfase_modulo_d1"] == 200.0
    assert dia["inicio_modulo_d1"] == 300.0
    # n_ciclos = 1,2,3,1,2,... cambia todos los días
    assert dia["dias_desde_cambio_n"] == 1
