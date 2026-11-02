from __future__ import annotations

from typing import Iterable

import pandas as pd

from riego_ml.config.schema import DataConfig, RunConfig


class DataValidationError(ValueError):
    """Raised when the dataset does not satisfy the expected schema."""


def _missing(columns: Iterable[str], available: Iterable[str]) -> list[str]:
    available_set = set(available)
    return [column for column in columns if column not in available_set]


def validate_raw_dataset(df: pd.DataFrame, config: RunConfig) -> None:
    data: DataConfig = config.data
    required = [
        data.date_column,
        data.group_column,
        *data.id_columns,
        data.nro_ciclo_column,
        data.cycle_volume_column,
        data.start_column,
        data.end_column,
        *data.environmental_features,
    ]
    missing = _missing(dict.fromkeys(required), df.columns)
    if missing:
        raise DataValidationError(
            "Faltan columnas obligatorias en el dataset: " + ", ".join(missing)
        )

    if df[data.date_column].isna().all():
        raise DataValidationError(f"La columna de fecha '{data.date_column}' está vacía.")
    if df[data.group_column].isna().all():
        raise DataValidationError(f"La columna de turno '{data.group_column}' está vacía.")

    duplicated = df.duplicated(
        subset=[data.date_column, *data.id_columns, data.nro_ciclo_column]
    )
    if duplicated.any():
        raise DataValidationError(
            f"Hay {int(duplicated.sum())} filas duplicadas por fecha/turno/ciclo."
        )

    numeric_columns = [data.cycle_volume_column, *data.environmental_features]
    for column in numeric_columns:
        converted = pd.to_numeric(df[column], errors="coerce")
        if converted.notna().sum() == 0:
            raise DataValidationError(
                f"La columna numérica '{column}' no contiene valores válidos."
            )


def validate_turno_dataset(
    df: pd.DataFrame, feature_columns: list[str], target_columns: list[str]
) -> None:
    if df.empty:
        raise DataValidationError("La tabla agregada por turno está vacía.")
    missing = _missing(feature_columns, df.columns)
    if missing:
        raise DataValidationError(
            "Faltan features en la tabla por turno: " + ", ".join(missing)
        )
    missing_targets = _missing(target_columns, df.columns)
    if missing_targets:
        raise DataValidationError(
            "Faltan targets en la tabla por turno: " + ", ".join(missing_targets)
        )
    overlap = sorted(set(feature_columns) & set(target_columns))
    if overlap:
        raise DataValidationError(
            "Hay fuga de información: columnas usadas como feature y target: "
            + ", ".join(overlap)
        )
