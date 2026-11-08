"""Conversión de WeatherLink v2 a las unidades con que se entrenó el modelo (°C, mm, km).

**Único lugar** con las reglas (decisión del usuario 2026-11-08, hallazgo H7 de la propuesta): si la
empresa cambia un criterio (qué campo es la T° Prom, la %HR o el viento), se cambia la tabla
:data:`REGLAS` y se corre ``python -m app.cli reprocesar-weatherlink --desde --hasta``, que vuelve a
derivar ``meteo_lectura`` desde los payloads guardados en ``ingesta_crudo`` sin volver a descargar.

La API entrega un registro cada 30 min en unidades imperiales (°F, pulgadas, millas) con ``ts`` =
**fin** del intervalo en segundos UTC. ``ml/data/raw/data_metereologica.xlsx`` (con el que se
entrenó) tiene las mismas lecturas ya convertidas; estas reglas lo reproducen (ver
``tests/test_weatherlink_conversion.py``, que mide la coincidencia sobre un mes real):

==========  ==============  ============================  =====================================
Columna     Campo de la API Conversión                    Redondeo
==========  ==============  ============================  =====================================
T (Prom)    temp_out_hi     (°F − 32) × 5/9               0,1 (la empresa usa el máximo del
                                                          intervalo como T° Prom)
T_max       temp_out_hi     (°F − 32) × 5/9               0,1
T_min       temp_out_lo     (°F − 32) × 5/9               0,1
HR (Prom)   hum_out         igual (%)                     —
HR_max      hum_out         igual (%)                     —
Rad         solar_rad_hi    igual (W/m²)                  —
ETo         et              pulgadas × 25,4 (mm)          0,01 (mitad hacia abajo, como el Excel)
Viento      wind_run        millas × 1,609344 (km/30 min) 0,01
Lluvia      rainfall_mm     igual (mm)                    —
DPV         temp_out,       Tetens con temp_out en °C     sin redondeo (temp_out a 0,1 °C
            hum_out         redondeada y hum_out          antes de calcular)
==========  ==============  ============================  =====================================

``fecha_hora`` = ``ts`` (fin del intervalo) pasado de UTC a la hora local de Lima, sin zona. El
registro de las 00:00 pertenece al día nuevo (``meteo_diaria`` corta con ``normalize()``), igual
que en el Excel.

La salida tiene el formato de ``riego_ml.sources.meteo`` (``Fundo``, ``fecha_hora`` y
``VARIABLES``); :func:`lecturas_saneadas` le aplica además ``sanear_meteo`` (rangos físicos,
sensor caído, grilla de 30 min): eso es lo que se guarda en ``meteo_lectura``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import pandas as pd
from riego_ml.sources.meteo import VARIABLES, sanear_meteo

from app.core.tiempo import zona_lima

# --- Conversiones de unidades ---------------------------------------------------

PULGADA_MM = Decimal("25.4")
MILLA_KM = Decimal("1.609344")


def fahrenheit_a_celsius(valor: Decimal) -> Decimal:
    return (valor - 32) * 5 / 9


def pulgadas_a_mm(valor: Decimal) -> Decimal:
    return valor * PULGADA_MM


def millas_a_km(valor: Decimal) -> Decimal:
    return valor * MILLA_KM


def igual(valor: Decimal) -> Decimal:
    return valor


@dataclass(frozen=True)
class Regla:
    """Cómo se obtiene una columna de ``meteo.py`` desde un campo de la API."""

    columna: str
    campo: str
    convertir: Callable[[Decimal], Decimal]
    decimales: int | None = None
    redondeo: str = ROUND_HALF_UP
    nota: str = ""


REGLAS: tuple[Regla, ...] = (
    Regla("T", "temp_out_hi", fahrenheit_a_celsius, 1,
          nota="T° Prom = máximo del intervalo (criterio de la empresa en el Excel)"),
    Regla("T_max", "temp_out_hi", fahrenheit_a_celsius, 1),
    Regla("T_min", "temp_out_lo", fahrenheit_a_celsius, 1),
    Regla("HR", "hum_out", igual, nota="%HR Prom = humedad del intervalo"),
    Regla("HR_max", "hum_out", igual),
    Regla("Rad", "solar_rad_hi", igual),
    Regla("ETo", "et", pulgadas_a_mm, 2, ROUND_HALF_DOWN),
    Regla("Viento", "wind_run", millas_a_km, 2, nota="km recorridos en el intervalo de 30 min"),
    Regla("Lluvia", "rainfall_mm", igual),
)

# DPV (kPa) por Tetens con la temperatura del intervalo en °C redondeada y la humedad.
DPV_CAMPO_TEMPERATURA = "temp_out"
DPV_DECIMALES_TEMPERATURA = 1
DPV_CAMPO_HUMEDAD = "hum_out"

CAMPO_TS = "ts"  # segundos UTC del fin del intervalo
CAMPOS_REQUERIDOS = frozenset(
    {CAMPO_TS, DPV_CAMPO_TEMPERATURA, DPV_CAMPO_HUMEDAD, *(r.campo for r in REGLAS)}
)


def _decimal(valor: Any) -> Decimal | None:
    if valor is None or (isinstance(valor, float) and math.isnan(valor)):
        return None
    try:
        numero = Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None
    return numero if numero.is_finite() else None


def _redondear(valor: Decimal, decimales: int | None, modo: str) -> float:
    if decimales is not None:
        valor = valor.quantize(Decimal(1).scaleb(-decimales), rounding=modo)
    return float(valor)


def aplicar_regla(regla: Regla, valor: Any) -> float:
    numero = _decimal(valor)
    if numero is None:
        return math.nan
    return _redondear(regla.convertir(numero), regla.decimales, regla.redondeo)


def dpv_tetens(temperatura_c: float, humedad: float) -> float:
    """Déficit de presión de vapor (kPa): ``es × (1 − HR/100)``, ``es`` por Tetens."""
    if math.isnan(temperatura_c) or math.isnan(humedad):
        return math.nan
    es = 0.6108 * math.exp(17.27 * temperatura_c / (temperatura_c + 237.3))
    return es * (1 - humedad / 100)


def dpv_de_registro(registro: Mapping[str, Any]) -> float:
    temperatura = _decimal(registro.get(DPV_CAMPO_TEMPERATURA))
    humedad = _decimal(registro.get(DPV_CAMPO_HUMEDAD))
    if temperatura is None or humedad is None:
        return math.nan
    celsius = _redondear(fahrenheit_a_celsius(temperatura), DPV_DECIMALES_TEMPERATURA, ROUND_HALF_UP)
    return dpv_tetens(celsius, float(humedad))


def fecha_hora_local(ts: Any) -> pd.Timestamp | None:
    """``ts`` (segundos UTC, fin del intervalo) -> hora local de Lima sin zona."""
    numero = _decimal(ts)
    if numero is None:
        return None
    instante = pd.Timestamp(int(numero), unit="s", tz="UTC").tz_convert(zona_lima())
    return instante.tz_localize(None)


# --- Payload de la API ----------------------------------------------------------

def registros_de_payload(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Registros de 30 min de la respuesta de ``/historic/{station_id}``.

    La respuesta trae ``sensors: [{lsid, sensor_type, data_structure_type, data: [...]}]``; se
    usan los sensores cuyos registros traen los campos de :data:`CAMPOS_REQUERIDOS` (la consola
    Vantage Pro2). Si un ``ts`` se repite, queda el primero.
    """
    vistos: set[Any] = set()
    registros: list[dict[str, Any]] = []
    for sensor in payload.get("sensors") or []:
        if not isinstance(sensor, Mapping):
            continue
        for registro in sensor.get("data") or []:
            if not isinstance(registro, Mapping) or not CAMPOS_REQUERIDOS <= registro.keys():
                continue
            if registro[CAMPO_TS] in vistos:
                continue
            vistos.add(registro[CAMPO_TS])
            registros.append(dict(registro))
    return registros


# --- Conversión -----------------------------------------------------------------

COLUMNAS_SALIDA = ["Fundo", "fecha_hora", *VARIABLES]


def convertir(registros: Iterable[Mapping[str, Any]] | pd.DataFrame, fundo: str) -> pd.DataFrame:
    """Registros crudos de la API (dicts o DataFrame con los campos) -> formato de ``meteo.py``
    (sin sanear). Los registros sin ``ts`` válido se descartan."""
    if isinstance(registros, pd.DataFrame):
        filas_entrada = registros.to_dict("records")
    else:
        filas_entrada = list(registros)
    filas = []
    for registro in filas_entrada:
        fecha_hora = fecha_hora_local(registro.get(CAMPO_TS))
        if fecha_hora is None:
            continue
        fila: dict[str, Any] = {"Fundo": fundo, "fecha_hora": fecha_hora}
        for regla in REGLAS:
            fila[regla.columna] = aplicar_regla(regla, registro.get(regla.campo))
        fila["DPV"] = dpv_de_registro(registro)
        filas.append(fila)
    df = pd.DataFrame(filas, columns=COLUMNAS_SALIDA)
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
    for columna in VARIABLES:
        df[columna] = pd.to_numeric(df[columna], errors="coerce").astype(float)
    return df


def lecturas_saneadas(
    registros: Iterable[Mapping[str, Any]] | pd.DataFrame, fundo: str
) -> tuple[pd.DataFrame, dict]:
    """Conversión + ``sanear_meteo``: las lecturas que se guardan en ``meteo_lectura``."""
    return sanear_meteo(convertir(registros, fundo))
