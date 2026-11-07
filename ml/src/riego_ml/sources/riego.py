"""Lectura del registro de riego (``data_riego.xlsx``, hoja ``MOD5``).

Es la tabla base del dataset: 1 fila por ciclo de riego ejecutado. Aquí solo
se normalizan nombres, tipos y horas; las reglas de descarte de ciclos viven en
``riego_ml.dataset.limpieza`` para que el dataset unido conserve todo el
registro original y se pueda auditar.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from riego_ml.utils.tiempo import MINUTOS_DIA, minutes_to_hhmm, norm_text, to_minutes

HOJA_RIEGO = "MOD5"

COLUMNAS_ORIGEN = {
    "fecha": "Fecha",
    "Fundo": "Fundo",
    "Modulo": "Modulo",
    "Turno": "Turno",
    "Valvula": "Valvula",
    "Hora Inicio": "hora_inicio_raw",
    "Hora Fin": "hora_fin_raw",
    "Tiempo de riego (minutos)": "duracion_min",
    "Cantidad de riego (m3)": "riego_m3",
    "Cantidad de riego (m3 por hectarea)": "riego_m3ha",
}

COLUMNAS_RIEGO = [
    "Fecha", "Fundo", "Modulo", "Turno", "Valvula",
    "inicio_min", "fin_min", "hora_inicio", "hora_fin", "fin_dia_siguiente",
    "duracion_min", "riego_m3", "riego_m3ha", "area_ha",
]


def leer_riego(path: str | Path, hoja: str = HOJA_RIEGO) -> tuple[pd.DataFrame, dict]:
    """Devuelve los ciclos de riego normalizados y un diagnóstico.

    ``inicio_min`` y ``fin_min`` son minutos desde las 00:00 de ``Fecha`` (día
    de inicio del ciclo); ``fin_min`` puede superar 1440 si el ciclo termina al
    día siguiente.
    """
    raw = pd.read_excel(path, sheet_name=hoja)
    faltantes = [c for c in COLUMNAS_ORIGEN if c not in raw.columns]
    if faltantes:
        raise ValueError(f"Faltan columnas en {path} [{hoja}]: {faltantes}")

    df = raw[list(COLUMNAS_ORIGEN)].rename(columns=COLUMNAS_ORIGEN)
    diag: dict = {"Riego: filas originales": len(df)}

    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.normalize()
    for columna in ("Fundo", "Modulo", "Turno"):
        df[columna] = norm_text(df[columna])
    for columna in ("duracion_min", "riego_m3", "riego_m3ha"):
        df[columna] = pd.to_numeric(df[columna], errors="coerce")

    df["inicio_min"] = df["hora_inicio_raw"].map(to_minutes)
    fin_reloj = df["hora_fin_raw"].map(to_minutes)

    invalidas = df["Fecha"].isna() | df["Turno"].isna() | df["inicio_min"].isna()
    diag["Riego: filas sin fecha/turno/hora de inicio (descartadas)"] = int(invalidas.sum())
    df = df[~invalidas].copy()
    fin_reloj = fin_reloj[~invalidas]

    # Si falta la duración se reconstruye con las horas (cruce de medianoche incluido).
    desde_horas = (fin_reloj - df["inicio_min"]) % MINUTOS_DIA
    sin_duracion = df["duracion_min"].isna()
    df.loc[sin_duracion, "duracion_min"] = desde_horas[sin_duracion]
    diag["Riego: duraciones reconstruidas desde las horas"] = int(sin_duracion.sum())
    diag["Riego: diferencias > 1 min entre 'Tiempo de riego' y horas"] = int(
        ((desde_horas - df["duracion_min"]).abs() > 1).sum()
    )

    df["fin_min"] = df["inicio_min"] + df["duracion_min"]
    df["hora_inicio"] = df["inicio_min"].map(minutes_to_hhmm)
    df["hora_fin"] = df["fin_min"].map(minutes_to_hhmm)
    df["fin_dia_siguiente"] = (df["fin_min"] >= MINUTOS_DIA).astype(int)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["area_ha"] = np.where(df["riego_m3ha"] > 0, df["riego_m3"] / df["riego_m3ha"], np.nan)

    df = df.sort_values(["Fecha", "Turno", "inicio_min"], kind="stable").reset_index(drop=True)
    diag["Riego: rango de fechas"] = f"{df['Fecha'].min():%Y-%m-%d} a {df['Fecha'].max():%Y-%m-%d}"
    diag["Riego: turnos"] = ", ".join(sorted(df["Turno"].dropna().unique()))
    return df[COLUMNAS_RIEGO], diag
