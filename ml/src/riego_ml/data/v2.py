from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from riego_ml.config.schema import RunConfig
from riego_ml.data.validation import DataValidationError


@dataclass
class V2Dataset:
    turno: pd.DataFrame
    ciclos: pd.DataFrame
    columns: dict[str, Any]


def _read_csv(path: Path | None, name: str) -> pd.DataFrame:
    if path is None:
        raise DataValidationError(f"Falta la ruta del dataset {name} (data.{name}).")
    frame = pd.read_csv(path)
    if frame.empty:
        raise DataValidationError(f"El dataset {name} está vacío: {path}")
    return frame


def _read_columns(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise DataValidationError(f"El archivo de columnas no es un objeto JSON: {path}")
    return data


def _require_columns(frame: pd.DataFrame, columns: list[str], name: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise DataValidationError(
            f"Faltan columnas obligatorias en {name}: " + ", ".join(missing)
        )


def _sort_frame(frame: pd.DataFrame, config: RunConfig) -> pd.DataFrame:
    sort_columns = [config.data.date_column, config.data.group_column]
    if config.data.cycle_column in frame.columns:
        sort_columns.append(config.data.cycle_column)
    sorted_frame = frame.copy()
    sorted_frame[config.data.date_column] = pd.to_datetime(
        sorted_frame[config.data.date_column]
    ).dt.strftime("%Y-%m-%d")
    return sorted_frame.sort_values(sort_columns, kind="stable").reset_index(drop=True)


def load_v2_dataset(config: RunConfig) -> V2Dataset:
    data = config.data
    turno = _read_csv(data.turno_file, "turno_file")
    ciclos = _read_csv(data.ciclos_file, "ciclos_file")
    columns = _read_columns(data.columns_file)

    _require_columns(turno, [data.date_column, data.group_column], "turno_dia")
    _require_columns(
        ciclos,
        [data.date_column, data.group_column, data.cycle_column],
        "ciclos",
    )
    target_turno = columns.get("target_turno_dia", "n_ciclos")
    _require_columns(turno, [target_turno], "turno_dia")
    target_cycle_columns = list(data.target_cycle_columns)
    _require_columns(ciclos, target_cycle_columns, "ciclos")

    turno = _sort_frame(turno, config)
    ciclos = _sort_frame(ciclos, config)

    turno["n_ciclos_clase"] = (
        pd.to_numeric(turno[target_turno], errors="coerce")
        .clip(upper=data.tail_class)
        .astype("float64")
    )
    ciclos["ciclo_slot"] = (
        pd.to_numeric(ciclos[data.cycle_column], errors="coerce")
        .clip(upper=data.max_cycles)
        .astype("float64")
    )

    for target in target_cycle_columns:
        values = pd.to_numeric(ciclos[target], errors="coerce")
        for slot in range(1, data.max_cycles + 1):
            column = f"target__{target}__{slot}"
            ciclos[column] = np.where(ciclos["ciclo_slot"] == slot, values, np.nan)

    return V2Dataset(turno=turno, ciclos=ciclos, columns=columns)


def turno_feature_columns(dataset: V2Dataset, config: RunConfig) -> list[str]:
    configured = dataset.columns.get("features_turno_dia", [])
    features = [str(column) for column in configured if column in dataset.turno.columns]
    if not features:
        excluded = {
            *config.data.id_columns,
            config.data.date_column,
            config.data.group_column,
            dataset.columns.get("target_turno_dia", "n_ciclos"),
            "n_ciclos_clase",
        }
        features = [
            column
            for column in dataset.turno.columns
            if column not in excluded
            and pd.api.types.is_numeric_dtype(dataset.turno[column])
        ]
    if not features:
        raise DataValidationError("No quedaron features para el modelo de turno/día.")
    return list(dict.fromkeys(features))


def ciclo_feature_columns(dataset: V2Dataset, config: RunConfig) -> list[str]:
    configured = [str(column) for column in dataset.columns.get("features_ciclo", [])]
    excluded = {
        config.data.cycle_column,
        "n_ciclos",
        "ciclo_slot",
        *config.data.target_cycle_columns,
        "fin_min",
        "hora_inicio",
        "hora_fin",
        "fin_dia_siguiente",
        *[f"target__{target}__{slot}" for target in config.data.target_cycle_columns for slot in range(1, config.data.max_cycles + 1)],
    }
    features = [
        column
        for column in configured
        if column in dataset.ciclos.columns and column not in excluded
    ]
    if not features:
        features = [
            column
            for column in dataset.ciclos.columns
            if column not in excluded
            and column not in config.data.id_columns
            and pd.api.types.is_numeric_dtype(dataset.ciclos[column])
        ]
    features.append("ciclo_slot")
    if not features:
        raise DataValidationError("No quedaron features para el modelo de ciclo.")
    return list(dict.fromkeys(features))
