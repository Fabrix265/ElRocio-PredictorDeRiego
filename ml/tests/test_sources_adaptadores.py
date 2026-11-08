"""D1: el saneamiento de meteo, Phytech y NDVI funciona sobre DataFrames (BD/API), sin archivos."""

import numpy as np
import pandas as pd

from riego_ml.sources.meteo import VARIABLES, meteo_diaria, sanear_meteo
from riego_ml.sources.ndvi import ndvi_diario
from riego_ml.sources.phytech import PLANTA_VARS, columnas_suelo_diario, resumir_phytech
from riego_ml.sources.phytech_crudo import HUM_COLS


def _lecturas(n=48, fundo=" ensueño 1 "):
    horas = pd.date_range("2025-01-02 00:30", periods=n, freq="30min")
    datos = {v: 1.0 for v in VARIABLES}
    datos.update(T=20.0, T_max=21.0, T_min=19.0, HR=80.0, HR_max=85.0, ETo=0.1, DPV=0.5)
    return pd.DataFrame({"Fundo": fundo, "fecha_hora": horas, **datos})


def test_sanear_meteo_aplica_rangos_sensor_caido_y_grilla():
    df = _lecturas(4)
    df.loc[0, ["T", "HR"]] = 0.0          # sensor caído: toda la lectura vacía
    df.loc[1, "Rad"] = 5000.0             # fuera de rango
    df.loc[2, "HR"] = 1.0                 # HR inválida -> DPV vacío
    extra = df.iloc[[3]].copy()
    extra["fecha_hora"] = extra["fecha_hora"] + pd.Timedelta(minutes=5)  # fuera de grilla
    extra["T"] = 22.0
    out, diag = sanear_meteo(pd.concat([df, extra], ignore_index=True))
    assert list(out.columns) == ["Fundo", "fecha_hora", *VARIABLES]
    assert out["Fundo"].unique().tolist() == ["ENSUEÑO 1"]
    assert len(out) == 4
    assert out.loc[0, VARIABLES].isna().all()
    assert np.isnan(out.loc[1, "Rad"])
    assert np.isnan(out.loc[2, "DPV"])
    assert out.loc[3, "T"] == 21.0       # promedio del bloque de 30 min
    assert diag["Meteo: lecturas fuera de la grilla de 30 min"] == 1


def test_sanear_meteo_y_meteo_diaria_con_lecturas_de_un_dia():
    lecturas, _ = sanear_meteo(_lecturas(48))
    diario, _ = meteo_diaria(lecturas)
    # 00:30 .. 23:30 del 02/01 y 00:00 del 03/01 (el registro de las 00:00 es del día nuevo)
    assert diario["Fecha"].dt.strftime("%Y-%m-%d").tolist() == ["2025-01-02", "2025-01-03"]
    assert diario.loc[0, "meteo_lecturas"] == 47
    assert diario.loc[0, "ETo_mm"] == round(0.1 * 48, 3)


def test_sanear_meteo_vacio():
    out, _ = sanear_meteo(_lecturas(0))
    assert out.empty and list(out.columns) == ["Fundo", "fecha_hora", *VARIABLES]


def _horario(horas, project_id=907557):
    fechas = pd.date_range("2025-01-02 00:00", periods=horas, freq="h")
    df = pd.DataFrame({"fundo": "ENSUEÑO 1", "project_id": project_id, "fecha_hora": fechas,
                       "hay_dato_phytech": 1})
    for c in [*HUM_COLS, "hum_zona_radicular", "hum_linea_estres"]:
        df[c] = 30.0
    return df


def _planta(dias, project_id=907557):
    return pd.DataFrame({"fundo": "ENSUEÑO 1", "project_id": project_id,
                         "fecha": pd.date_range("2025-01-02", periods=dias, freq="D"),
                         **{c: 1.0 for c in PLANTA_VARS}})


def test_resumir_phytech_desde_dataframes():
    horario = _horario(24)
    horario.loc[23, "hum_45cm"] = 40.0
    diario = resumir_phytech(horario, _planta(1))
    assert list(diario.columns) == ["Fundo", "Fecha", *columnas_suelo_diario(), *PLANTA_VARS]
    fila = diario.iloc[0]
    assert fila["suelo_horas"] == 24
    assert fila["hum_45cm_cierre"] == round((30 + 30 + 40) / 3, 3)
    assert fila["hum_45cm_rango"] == 10.0
    assert fila["mds_contraccion_um"] == 1.0


def test_resumir_phytech_otro_sensor_o_vacio():
    assert resumir_phytech(_horario(24, project_id=1), _planta(1, project_id=1)).empty
    solo_planta = resumir_phytech(_horario(0), _planta(2))
    assert len(solo_planta) == 2 and solo_planta["suelo_horas"].isna().all()


def test_ndvi_diario_desde_dataframe():
    imagenes = pd.DataFrame({
        "entity_id": [70208, 70208, 1], "date": ["2025-01-02", "2025-01-03", "2025-01-02"],
        "no_vegetation": [False, True, False],
        **{f"class{k}_ndvi_min": [0.1 * k] * 3 for k in range(5)},
        **{f"class{k}_ndvi_max": [0.1 * k + 0.1] * 3 for k in range(5)},
        **{f"class{k}_percent": [20.0] * 3 for k in range(5)},
    })
    out = ndvi_diario(imagenes, 70208, "ensueño 1")
    assert len(out) == 1
    assert out.loc[0, "Fundo"] == "ENSUEÑO 1"
    assert out.loc[0, "ndvi_medio"] == 0.25
    assert ndvi_diario(imagenes.iloc[0:0], 70208, "ensueño 1").empty
