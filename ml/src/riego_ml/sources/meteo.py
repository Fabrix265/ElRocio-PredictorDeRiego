"""Lectura y saneamiento de la estación meteorológica (``data_metereologica.xlsx``).

La estación registra cada 30 min. El saneamiento se hace sobre las lecturas
(antes de agregar), porque un sensor caído reporta ceros que, sumados, falsean
la ETo y la lluvia del día:

1. Lecturas fuera de la grilla de 30 min (p. ej. 00:05, 23:12) se asignan a su
   bloque de 30 min y se promedian con la lectura del bloque -> sin duplicados.
2. Sensor caído (T = 0 y HR = 0 a la vez) -> toda la lectura vacía.
3. Rangos físicos por variable (fuera de rango -> vacío, no se interpola).
4. El DPV se anula si la temperatura o la humedad de esa lectura son inválidas.
5. Agregado diario: con menos de ``MIN_LECTURAS_DIA`` lecturas válidas la
   variable del día queda vacía; la ETo diaria se reescala a 48 lecturas.

Lectura y saneamiento están separados: :func:`leer_meteo` lee el Excel y
:func:`sanear_meteo` aplica las reglas 1-4 a cualquier DataFrame con el mismo
formato (lecturas guardadas en la BD o convertidas desde la API de WeatherLink).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from riego_ml.utils.tiempo import norm_text, to_minutes

LECTURAS_DIA = 48
MIN_LECTURAS_DIA = 36   # 75 % del día

COLUMNAS_ORIGEN = {
    "Fundo": "Fundo",
    "Fecha": "Fecha",
    "Hora": "Hora",
    "T° Prom": "T",
    "T° Máx": "T_max",
    "T° Mín": "T_min",
    "Rad Solar Max": "Rad",
    "ETO": "ETo",
    "%HR Max": "HR_max",
    "%HR Prom": "HR",
    "DPV": "DPV",
    "Viento": "Viento",
    "Lluvia": "Lluvia",
}

# Rangos físicos válidos por lectura de 30 min
RANGOS = {
    "T": (5.0, 45.0),
    "T_max": (5.0, 45.0),
    "T_min": (5.0, 45.0),
    "HR": (5.0, 100.0),
    "HR_max": (5.0, 100.0),
    "Rad": (0.0, 1500.0),
    "ETo": (0.0, 0.8),
    "DPV": (0.0, 6.0),
    "Viento": (0.0, 30.0),
    "Lluvia": (0.0, 50.0),
}
VARIABLES = list(RANGOS)

COLUMNAS_DIARIAS = [
    "T_media", "T_max", "T_min", "HR_media", "HR_min", "HR_max", "ETo_mm",
    "DPV_media", "DPV_max", "Viento_media", "Lluvia_mm", "Rad_max", "Rad_media",
    "horas_T30", "meteo_lecturas",
]
UMBRAL_CALOR = 30.0  # °C


def leer_meteo(path: str | Path, header: int = 2) -> tuple[pd.DataFrame, dict]:
    """Lecturas de 30 min saneadas (1 fila por Fundo y bloque de 30 min).

    Solo lee el archivo (columnas de ``COLUMNAS_ORIGEN`` y ``fecha_hora`` desde Fecha + Hora);
    el saneamiento es :func:`sanear_meteo`, que también se aplica a lecturas de la BD o la API.
    """
    raw = pd.read_excel(path, header=header)
    faltantes = [c for c in COLUMNAS_ORIGEN if c not in raw.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas en {path}: {faltantes}")
    df = raw[list(COLUMNAS_ORIGEN)].rename(columns=COLUMNAS_ORIGEN)
    fecha = pd.to_datetime(df["Fecha"], errors="coerce").dt.normalize()
    minutos = df["Hora"].map(to_minutes)
    df["fecha_hora"] = fecha + pd.to_timedelta(minutos, unit="min")
    return sanear_meteo(df)


def sanear_meteo(lecturas: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Aplica las reglas 1-4 a lecturas con ``Fundo``, ``fecha_hora`` y las ``VARIABLES``.

    Devuelve 1 fila por Fundo y bloque de 30 min con ``Fundo``, ``fecha_hora`` y ``VARIABLES``.
    """
    df = lecturas.copy()
    diag: dict = {"Meteo: lecturas originales": len(df)}

    df["Fundo"] = norm_text(df["Fundo"])
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"], errors="coerce")
    df = df.dropna(subset=["Fundo", "fecha_hora"]).copy()
    for columna in VARIABLES:
        df[columna] = pd.to_numeric(df[columna], errors="coerce")

    caido = (df["T"] == 0) & (df["HR"] == 0)
    df.loc[caido, VARIABLES] = np.nan
    diag["Meteo: lecturas con sensor caído (T=0 y HR=0)"] = int(caido.sum())

    t_mala = df["T"].notna() & ~df["T"].between(*RANGOS["T"])
    hr_mala = df["HR"].notna() & ~df["HR"].between(*RANGOS["HR"])
    for columna, (minimo, maximo) in RANGOS.items():
        malo = df[columna].notna() & ~df[columna].between(minimo, maximo)
        diag[f"Meteo: {columna} fuera de [{minimo}, {maximo}]"] = int(malo.sum())
        df.loc[malo, columna] = np.nan
    df.loc[t_mala | hr_mala, "DPV"] = np.nan

    fuera_grilla = df["fecha_hora"] != df["fecha_hora"].dt.floor("30min")
    diag["Meteo: lecturas fuera de la grilla de 30 min"] = int(fuera_grilla.sum())
    df["fecha_hora"] = df["fecha_hora"].dt.floor("30min")
    df = df.groupby(["Fundo", "fecha_hora"], as_index=False)[VARIABLES].mean()
    diag["Meteo: lecturas tras unificar bloques de 30 min"] = len(df)
    return df, diag


def meteo_diaria(lecturas: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Agrega las lecturas de 30 min a 1 fila por Fundo y día."""
    df = lecturas.copy()
    df["Fecha"] = df["fecha_hora"].dt.normalize()
    grupos = df.groupby(["Fundo", "Fecha"])
    conteo = grupos[VARIABLES].count()
    diario = pd.DataFrame(
        {
            "T_media": grupos["T"].mean(),
            "T_max": grupos["T_max"].max(),
            "T_min": grupos["T_min"].min(),
            "HR_media": grupos["HR"].mean(),
            "HR_min": grupos["HR"].min(),
            "HR_max": grupos["HR_max"].max(),
            "ETo_mm": grupos["ETo"].mean() * LECTURAS_DIA,
            "DPV_media": grupos["DPV"].mean(),
            "DPV_max": grupos["DPV"].max(),
            "Viento_media": grupos["Viento"].mean(),
            "Lluvia_mm": grupos["Lluvia"].sum(),
            "Rad_max": grupos["Rad"].max(),
            "Rad_media": grupos["Rad"].mean(),
            # Horas del día con temperatura sobre el umbral (lecturas de 30 min).
            "horas_T30": df.assign(_c=df["T"] > UMBRAL_CALOR).groupby(["Fundo", "Fecha"])["_c"].sum() * 0.5,
            "meteo_lecturas": grupos["T"].size(),
        }
    )
    origen = {
        "T_media": "T", "T_max": "T_max", "T_min": "T_min", "HR_media": "HR",
        "HR_min": "HR", "HR_max": "HR_max", "ETo_mm": "ETo", "DPV_media": "DPV",
        "DPV_max": "DPV", "Viento_media": "Viento", "Lluvia_mm": "Lluvia",
        "Rad_max": "Rad", "Rad_media": "Rad", "horas_T30": "T",
    }
    incompletos = 0
    for destino, fuente in origen.items():
        pocas = conteo[fuente] < MIN_LECTURAS_DIA
        incompletos += int(pocas.sum())
        diario.loc[pocas, destino] = np.nan
    diario = diario.round(3).reset_index()
    diag = {
        "Meteo: días": len(diario),
        "Meteo: rango de fechas": f"{diario['Fecha'].min():%Y-%m-%d} a {diario['Fecha'].max():%Y-%m-%d}",
        "Meteo: días con ETo vacía (< 75 % de lecturas)": int(diario["ETo_mm"].isna().sum()),
        "Meteo: valores diarios anulados por día incompleto": incompletos,
    }
    return diario[["Fundo", "Fecha", *COLUMNAS_DIARIAS]], diag
