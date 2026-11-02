from __future__ import annotations

import datetime as dt
import re
from typing import Any

import numpy as np
import pandas as pd

from riego_ml.config.schema import RunConfig

_TIME_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}(?:\.\d+)?))?\s*$")


def parse_time_to_minutes(value: Any) -> float:
    if value is None:
        return np.nan
    try:
        if pd.isna(value):
            return np.nan
    except (TypeError, ValueError):
        pass

    if isinstance(value, dt.time):
        return value.hour * 60 + value.minute + value.second / 60 + value.microsecond / 60_000_000
    if isinstance(value, dt.datetime):
        return (
            value.hour * 60
            + value.minute
            + value.second / 60
            + value.microsecond / 60_000_000
        )
    if isinstance(value, (int, float, np.integer, np.floating)):
        numeric = float(value)
        if np.isnan(numeric):
            return np.nan
        if 0 <= numeric < 1:
            return numeric * 24 * 60
        if 0 <= numeric <= 24 * 60:
            return numeric
        return np.nan

    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return np.nan
    match = _TIME_RE.match(text)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = float(match.group(3) or 0)
        return hours * 60 + minutes + seconds / 60

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return np.nan
    return parsed.hour * 60 + parsed.minute + parsed.second / 60


def minutes_to_hhmm(value: float | None) -> str | None:
    if value is None or pd.isna(value):
        return None
    total = int(round(float(value))) % (24 * 60)
    return f"{total // 60:02d}:{total % 60:02d}"


def _clean_text(series: pd.Series) -> pd.Series:
    cleaned = series.astype("string").str.strip()
    cleaned = cleaned.replace({"": pd.NA, "nan": pd.NA, "None": pd.NA})
    return cleaned


def prepare_cycle_data(df: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    data = config.data
    work = df.copy()

    work[data.date_column] = pd.to_datetime(work[data.date_column], errors="coerce")
    work = work.dropna(subset=[data.date_column]).copy()
    if work.empty:
        raise ValueError("No quedaron filas con fecha válida.")

    for column in data.id_columns:
        if column == data.date_column:
            continue
        work[column] = _clean_text(work[column])

    work[data.nro_ciclo_column] = pd.to_numeric(
        work[data.nro_ciclo_column], errors="coerce"
    )
    work = work.dropna(subset=[data.nro_ciclo_column]).copy()
    work[data.nro_ciclo_column] = work[data.nro_ciclo_column].astype(int)

    work[data.cycle_volume_column] = pd.to_numeric(
        work[data.cycle_volume_column], errors="coerce"
    )
    for column in data.environmental_features:
        work[column] = pd.to_numeric(work[column], errors="coerce")

    work["hora_inicio_min"] = work[data.start_column].map(parse_time_to_minutes)
    work["hora_fin_min"] = work[data.end_column].map(parse_time_to_minutes)
    work = work.dropna(subset=["hora_inicio_min", "hora_fin_min"]).copy()
    if work.empty:
        raise ValueError("No quedaron filas con horas de inicio/fin válidas.")

    duration = work["hora_fin_min"] - work["hora_inicio_min"]
    duration = duration.where(duration >= 0, duration + 24 * 60)
    work["tiempo_ciclo_min"] = duration
    work.loc[work["tiempo_ciclo_min"] > 24 * 60, "tiempo_ciclo_min"] = np.nan

    work = work.dropna(subset=["tiempo_ciclo_min"]).copy()
    if work.empty:
        raise ValueError("No quedaron ciclos con duración válida.")

    sort_columns = [data.date_column, *data.id_columns, data.nro_ciclo_column]
    work = work.sort_values(sort_columns).reset_index(drop=True)
    return work
