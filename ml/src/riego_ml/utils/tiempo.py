"""Conversión de horas de Excel a minutos y de minutos a texto HH:MM."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

MINUTOS_DIA = 1440


def to_minutes(value: object) -> float:
    """Convierte una hora a minutos desde las 00:00.

    Acepta ``datetime.time``, ``datetime`` y texto ``HH:MM[:SS]``. Excel guarda
    las horas mayores a 24:00 como ``1900-01-01 HH:MM`` (día 1 = +24 h): en ese
    caso se suman los días completos para conservar el cruce de medianoche.
    """
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (dt.datetime, pd.Timestamp)):
        extra_days = 0
        if value.year == 1900 and value.month == 1:
            extra_days = value.day  # 1900-01-01 equivale a "+1 día" en Excel
        elif value.year == 1899:
            extra_days = 0
        return (
            extra_days * MINUTOS_DIA
            + value.hour * 60
            + value.minute
            + value.second / 60
            + value.microsecond / 60_000_000
        )
    if isinstance(value, dt.time):
        return value.hour * 60 + value.minute + value.second / 60 + value.microsecond / 60_000_000
    if isinstance(value, (int, float, np.number)):
        # Fracción de día (formato numérico de Excel)
        return float(value) * MINUTOS_DIA
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return np.nan
    parsed = pd.to_datetime(text, errors="coerce", format="mixed")
    if pd.isna(parsed):
        return np.nan
    return parsed.hour * 60 + parsed.minute + parsed.second / 60


def minutes_to_hhmm(minutes: float) -> str:
    """Minutos desde las 00:00 del día de inicio -> 'HH:MM' (módulo 24 h)."""
    if minutes is None or pd.isna(minutes):
        return ""
    total = int(round(float(minutes))) % MINUTOS_DIA
    return f"{total // 60:02d}:{total % 60:02d}"


def norm_text(series: pd.Series) -> pd.Series:
    """Texto sin espacios sobrantes y en mayúsculas (llaves Fundo/Turno)."""
    return series.astype("string").str.strip().str.upper()
