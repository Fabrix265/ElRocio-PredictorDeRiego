from __future__ import annotations

import re
from typing import Any

import numpy as np
import pandas as pd

from riego_ml.config.schema import RunConfig

_TRAILING_NUMBER = re.compile(r"(\d+)\s*$")


def _group_keys(config: RunConfig) -> list[str]:
    keys: list[str] = []
    for column in [config.data.date_column, *config.data.id_columns]:
        if column not in keys:
            keys.append(column)
    if config.data.group_column not in keys:
        keys.append(config.data.group_column)
    return keys


def _turno_order(turno: Any) -> float:
    text = str(turno)
    match = _TRAILING_NUMBER.search(text)
    if match:
        return float(match.group(1))
    return np.nan


def _daily_environment(turno_source: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    date_column = config.data.date_column
    env_columns = config.data.environmental_features
    if not env_columns:
        return pd.DataFrame({date_column: turno_source[date_column].drop_duplicates()})

    grouped = turno_source.groupby(date_column, dropna=False)
    pieces = []
    for column in env_columns:
        agg = grouped[column].agg(["mean", "min", "max", "std"])
        agg.columns = [
            f"{column}_mean",
            f"{column}_min",
            f"{column}_max",
            f"{column}_std",
        ]
        pieces.append(agg)
    daily = pd.concat(pieces, axis=1).reset_index()
    return daily


def aggregate_to_turno(cycle_df: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    data = config.data
    keys = _group_keys(config)
    date_column = data.date_column
    nro_column = data.nro_ciclo_column
    volume_column = data.cycle_volume_column
    max_cycles = data.max_cycles

    source = cycle_df.copy()
    source["Turno_orden"] = source[data.group_column].map(_turno_order)
    source["Turno_orden"] = source.groupby(
        [date_column, *[c for c in data.id_columns if c not in {date_column, data.group_column}]],
        dropna=False,
    )["Turno_orden"].transform(
        lambda values: values.fillna(
            pd.Series(np.arange(1, len(values) + 1), index=values.index)
        )
    )
    source["Turno_orden"] = pd.to_numeric(source["Turno_orden"], errors="coerce")

    daily_env = _daily_environment(source, config)

    rows: list[dict[str, Any]] = []
    for key_values, group in source.groupby(keys, dropna=False, sort=True):
        if not isinstance(key_values, tuple):
            key_values = (key_values,)
        base = dict(zip(keys, key_values))
        group = group.sort_values(nro_column)

        n_ciclos = int(group[nro_column].max())
        if n_ciclos < 1:
            continue

        row: dict[str, Any] = dict(base)
        row["N_ciclos"] = n_ciclos
        row["Riego_total_m3"] = float(group[volume_column].fillna(0).sum())
        row["Turno_orden"] = float(group["Turno_orden"].dropna().iloc[0]) if group["Turno_orden"].notna().any() else np.nan

        for slot in range(1, max_cycles + 1):
            cycle = group[group[nro_column] == slot]
            if cycle.empty:
                row[f"Riego_ciclo_{slot}_m3"] = np.nan
                row[f"Hora_inicio_{slot}_min"] = np.nan
                row[f"Tiempo_ciclo_{slot}_min"] = np.nan
                row[f"Hora_fin_{slot}_min"] = np.nan
                continue
            cycle_row = cycle.iloc[0]
            row[f"Riego_ciclo_{slot}_m3"] = float(cycle_row[volume_column]) if pd.notna(cycle_row[volume_column]) else np.nan
            row[f"Hora_inicio_{slot}_min"] = float(cycle_row["hora_inicio_min"])
            row[f"Tiempo_ciclo_{slot}_min"] = float(cycle_row["tiempo_ciclo_min"])
            row[f"Hora_fin_{slot}_min"] = float(cycle_row["hora_fin_min"])

        rows.append(row)

    turno_df = pd.DataFrame(rows)
    if turno_df.empty:
        raise ValueError("La agregación por turno no generó filas.")

    turno_df = turno_df.merge(daily_env, on=date_column, how="left")

    date_series = pd.to_datetime(turno_df[date_column], errors="coerce")
    turno_df["anio"] = date_series.dt.year
    turno_df["mes"] = date_series.dt.month
    turno_df["dia"] = date_series.dt.day
    turno_df["dia_anio"] = date_series.dt.dayofyear
    turno_df["dia_semana"] = date_series.dt.dayofweek
    turno_df["semana_iso"] = date_series.dt.isocalendar().week.astype("Int64")

    sort_columns = [date_column, *[c for c in data.id_columns if c != date_column]]
    turno_df = turno_df.sort_values(sort_columns).reset_index(drop=True)
    return turno_df
