"""Conversión de WeatherLink (°F, pulgadas, millas) a las unidades del entrenamiento (°C, mm, km)."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from riego_ml.sources.meteo import meteo_diaria

from app.integraciones.weatherlink import conversion

RAIZ_ML = Path(__file__).resolve().parents[2] / "ml" / "data" / "raw"
EXCEL_METEO = RAIZ_ML / "data_metereologica.xlsx"
WL_2021 = RAIZ_ML / "WeatherLink" / "completo" / (
    "Historic_tipo24-Vantage-Pro2-Plus-Cabled_ds4_2021_est28494.xlsx"
)
# Desde el 13-sep-2021 el Excel pone la lectura de las 24:00 en el día que termina (ver
# conversion.MEDIANOCHE_AL_DIA_QUE_TERMINA): se coteja un mes posterior.
MES_COTEJO = "2021-11"

# 2021-01-01 12:00 de Lima (fin del intervalo) = 17:00 UTC.
REGISTRO_MEDIODIA = {
    "ts": 1609520400, "temp_out": 81.8, "temp_out_hi": 82.9, "temp_out_lo": 81.0, "hum_out": 55,
    "solar_rad_hi": 1010, "et": 0.019, "wind_run": 0.5, "rainfall_mm": 0.0,
}


def test_registro_conocido_coincide_con_el_excel():
    df = conversion.convertir([REGISTRO_MEDIODIA], "ENSUEÑO 1")
    fila = df.iloc[0]
    assert fila["fecha_hora"] == pd.Timestamp("2021-01-01 12:00")
    assert fila["T"] == 28.3 and fila["T_max"] == 28.3       # 82,9 °F
    assert fila["T_min"] == 27.2                            # 81,0 °F
    assert fila["ETo"] == 0.48                              # 0,019 pulgadas
    assert fila["Viento"] == 0.80                           # 0,5 millas
    assert fila["HR"] == fila["HR_max"] == 55
    assert fila["Rad"] == 1010 and fila["Lluvia"] == 0
    assert fila["DPV"] == pytest.approx(1.67, abs=0.005)    # Tetens con 27,7 °C y 55 %


def test_redondeos_y_valores_faltantes():
    assert conversion.aplicar_regla(conversion.REGLAS[0], 69.5) == 20.8   # verificado en H7
    eto = next(r for r in conversion.REGLAS if r.columna == "ETo")
    assert conversion.aplicar_regla(eto, 0.025) == 0.63      # 0,635: mitad hacia abajo (Excel)
    assert math.isnan(conversion.aplicar_regla(eto, None))
    assert math.isnan(conversion.aplicar_regla(eto, "x"))
    sin_temp = dict(REGISTRO_MEDIODIA, temp_out=None)
    assert math.isnan(conversion.convertir([sin_temp], "F").iloc[0]["DPV"])
    sin_ts = dict(REGISTRO_MEDIODIA, ts=None)
    assert conversion.convertir([sin_ts], "F").empty


def test_tabla_de_reglas_cubre_todas_las_variables():
    from riego_ml.sources.meteo import VARIABLES

    assert sorted([r.columna for r in conversion.REGLAS] + ["DPV"]) == sorted(VARIABLES)


def test_registro_de_las_24_pertenece_al_dia_que_termina():
    """El de ``ts`` local 00:00 cierra el día anterior: se etiqueta ``D 00:00`` (como el Excel desde
    el 13-sep-2021) y ``meteo_diaria`` lo suma a ``D``."""
    medianoche = 1609477200  # 2021-01-01 00:00 Lima
    registros = [dict(REGISTRO_MEDIODIA, ts=medianoche + 1800 * k) for k in range(0, 50)]
    lecturas, _ = conversion.lecturas_saneadas(registros, "ENSUEÑO 1")
    etiquetas = set(lecturas["fecha_hora"])
    assert pd.Timestamp("2020-12-31 00:00") in etiquetas    # ts 2021-01-01 00:00
    assert pd.Timestamp("2021-01-01 00:00") in etiquetas    # ts 2021-01-02 00:00
    assert pd.Timestamp("2021-01-02 00:00") not in etiquetas
    diario, _ = meteo_diaria(lecturas)
    conteo = dict(zip(diario["Fecha"].dt.strftime("%Y-%m-%d"), diario["meteo_lecturas"]))
    assert conteo == {"2020-12-31": 1, "2021-01-01": 48, "2021-01-02": 1}
    assert conversion.dia_de_registro({"ts": medianoche}) == pd.Timestamp("2020-12-31").date()
    assert conversion.dia_de_registro({"ts": medianoche + 1800}) == pd.Timestamp("2021-01-01").date()
    assert conversion.dia_de_registro({"ts": None}) is None


def test_corte_de_dia_configurable(monkeypatch):
    monkeypatch.setattr(conversion, "MEDIANOCHE_AL_DIA_QUE_TERMINA", False)
    assert conversion.fecha_hora_local(1609477200) == pd.Timestamp("2021-01-01 00:00")


def test_registros_de_payload_toma_el_sensor_de_la_consola():
    payload = {
        "station_id": 28494,
        "sensors": [
            {"lsid": 1, "sensor_type": 504, "data": [{"ts": 1, "bar": 30.1}]},
            {"lsid": 2, "sensor_type": 24, "data_structure_type": 4,
             "data": [REGISTRO_MEDIODIA, REGISTRO_MEDIODIA, dict(REGISTRO_MEDIODIA, ts=1609522200)]},
        ],
    }
    registros = conversion.registros_de_payload(payload)
    assert [r["ts"] for r in registros] == [1609520400, 1609522200]
    assert conversion.registros_de_payload({}) == []


def test_lecturas_saneadas_aplica_los_rangos_de_meteo():
    caliente = dict(REGISTRO_MEDIODIA, temp_out_hi=140.0)  # 60 °C: fuera de rango
    lecturas, diag = conversion.lecturas_saneadas([caliente], "ENSUEÑO 1")
    assert math.isnan(lecturas.iloc[0]["T"])
    assert diag["Meteo: T fuera de [5.0, 45.0]"] == 1


@pytest.mark.skipif(not (EXCEL_METEO.exists() and WL_2021.exists()), reason="sin ml/data/raw")
def test_coincidencia_con_data_metereologica_en_un_mes_real():
    """Convierte los registros crudos de la API de enero 2021 y los compara con el Excel de
    entrenamiento en el mismo instante. Las diferencias que quedan son lecturas que en el Excel
    vienen de otra fuente (promedios), no de las fórmulas."""
    crudo = pd.read_excel(WL_2021)
    convertido = conversion.convertir(crudo, "ENSUEÑO 1")
    convertido = convertido[convertido["fecha_hora"].dt.strftime("%Y-%m") == MES_COTEJO]

    excel = pd.read_excel(EXCEL_METEO, header=2)
    excel.columns = ["Fundo", "Fecha", "Hora", "T", "T_max", "T_min", "Rad", "ETo", "HR_max", "HR",
                     "DPV", "Viento", "Lluvia"]
    hora = pd.to_timedelta(excel["Hora"].astype(str))
    excel["fecha_hora"] = pd.to_datetime(excel["Fecha"]).dt.normalize() + hora
    cruce = convertido.merge(excel, on="fecha_hora", suffixes=("_api", "_excel"))
    assert len(cruce) >= 0.99 * len(convertido) > 1400

    coincidencia = {}
    for columna in [r.columna for r in conversion.REGLAS] + ["DPV"]:
        tolerancia = 0.005 if columna == "DPV" else 1e-9
        iguales = np.isclose(cruce[f"{columna}_api"], cruce[f"{columna}_excel"], atol=tolerancia,
                             equal_nan=True)
        coincidencia[columna] = round(float(iguales.mean()) * 100, 2)
    a_medianoche = cruce[cruce["fecha_hora"].dt.hour.eq(0) & cruce["fecha_hora"].dt.minute.eq(0)]
    coincidencia["medianoche"] = round(float(
        (np.isclose(a_medianoche["T_api"], a_medianoche["T_excel"])
         & np.isclose(a_medianoche["HR_api"], a_medianoche["HR_excel"])).mean()) * 100, 2)
    print(f"\nCoincidencia WeatherLink vs data_metereologica.xlsx ({MES_COTEJO}, {len(cruce)} "
          f"registros): {coincidencia}")
    for columna, porcentaje in coincidencia.items():
        assert porcentaje >= 95, (columna, porcentaje)
    for columna in ("T_max", "Rad", "ETo", "Lluvia", "medianoche"):
        assert coincidencia[columna] >= 99, (columna, coincidencia[columna])
