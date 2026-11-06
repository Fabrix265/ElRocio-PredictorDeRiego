from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupShuffleSplit, train_test_split

from riego_ml.config.schema import RunConfig


@dataclass
class SplitIndices:
    train: np.ndarray
    validation: np.ndarray
    test: np.ndarray
    strategy: str
    seed: int


@dataclass
class TemporalBoundaries:
    train_dates: np.ndarray = field(default_factory=lambda: np.array([]))
    validation_dates: np.ndarray = field(default_factory=lambda: np.array([]))
    test_dates: np.ndarray = field(default_factory=lambda: np.array([]))


def _classes(values: pd.Series) -> set[Any]:
    return set(values.dropna().unique().tolist())


def _try_group_split(
    df: pd.DataFrame,
    group_column: str,
    stratify_column: str | None,
    test_size: float,
    validation_size: float,
    seed: int,
    required_classes: set[Any],
) -> SplitIndices | None:
    groups = df[group_column]
    if groups.nunique() < 4:
        return None

    first = GroupShuffleSplit(n_splits=1, test_size=test_size, random_state=seed)
    train_val_idx, test_idx = next(first.split(df, groups=groups))

    train_val = df.iloc[train_val_idx]
    val_fraction = validation_size / (1.0 - test_size) if validation_size > 0 else 0.0
    if val_fraction <= 0:
        train_idx = train_val_idx
        validation_idx = np.array([], dtype=int)
    else:
        second = GroupShuffleSplit(
            n_splits=1, test_size=val_fraction, random_state=seed + 1
        )
        train_rel, validation_rel = next(
            second.split(train_val, groups=train_val[group_column])
        )
        train_idx = train_val_idx[train_rel]
        validation_idx = train_val_idx[validation_rel]

    if stratify_column is not None and stratify_column in df.columns:
        train_classes = _classes(df.iloc[train_idx][stratify_column])
        validation_classes = _classes(df.iloc[validation_idx][stratify_column])
        test_classes = _classes(df.iloc[test_idx][stratify_column])
        if not required_classes.issubset(train_classes):
            return None
        if len(validation_classes) < 2 or len(test_classes) < 2:
            return None

    if set(df.iloc[train_idx][group_column]) & set(df.iloc[test_idx][group_column]):
        return None
    if set(df.iloc[train_idx][group_column]) & set(df.iloc[validation_idx][group_column]):
        return None
    return SplitIndices(
        train=np.asarray(train_idx),
        validation=np.asarray(validation_idx),
        test=np.asarray(test_idx),
        strategy="group_shuffle",
        seed=seed,
    )


def _fallback_random_split(
    df: pd.DataFrame,
    stratify_column: str | None,
    test_size: float,
    validation_size: float,
    seed: int,
) -> SplitIndices:
    stratify = df[stratify_column] if stratify_column in df.columns else None
    train_val_idx, test_idx = train_test_split(
        np.arange(len(df)),
        test_size=test_size,
        random_state=seed,
        stratify=stratify,
    )
    val_fraction = validation_size / (1.0 - test_size) if validation_size > 0 else 0.0
    if val_fraction <= 0:
        train_idx = train_val_idx
        validation_idx = np.array([], dtype=int)
    else:
        stratify_train_val = (
            df.iloc[train_val_idx][stratify_column]
            if stratify_column in df.columns
            else None
        )
        train_idx, validation_idx = train_test_split(
            train_val_idx,
            test_size=val_fraction,
            random_state=seed + 1,
            stratify=stratify_train_val,
        )
    return SplitIndices(
        train=np.asarray(train_idx),
        validation=np.asarray(validation_idx),
        test=np.asarray(test_idx),
        strategy="random",
        seed=seed,
    )


def _dates(df: pd.DataFrame, column: str) -> np.ndarray:
    values = pd.to_datetime(df[column], errors="coerce").dt.normalize()
    return np.sort(values.dropna().unique())


def temporal_boundaries(df: pd.DataFrame, config: RunConfig) -> TemporalBoundaries:
    split = config.split
    date_column = split.group_column or config.data.date_column
    dates = _dates(df, date_column)
    total = len(dates)
    if total < 10:
        raise ValueError(
            "Se necesitan al menos 10 fechas distintas para el split temporal."
        )

    n_test = max(1, int(round(total * split.test_size)))
    n_validation = max(1, int(round(total * split.validation_size))) if split.validation_size > 0 else 0
    gap = max(0, int(split.gap_days))

    test_start = max(0, total - n_test)
    validation_end = max(0, test_start - gap)
    validation_start = max(0, validation_end - n_validation)
    train_end = max(0, validation_start - gap)

    if train_end <= 0:
        raise ValueError(
            "El split temporal dejó el conjunto de train vacío; reduce test_size, "
            "validation_size o gap_days."
        )

    return TemporalBoundaries(
        train_dates=dates[:train_end],
        validation_dates=dates[validation_start:validation_end],
        test_dates=dates[test_start:],
    )


def split_from_boundaries(
    df: pd.DataFrame,
    boundaries: TemporalBoundaries,
    config: RunConfig,
) -> SplitIndices:
    split = config.split
    date_column = split.group_column or config.data.date_column
    dates = pd.to_datetime(df[date_column], errors="coerce").dt.normalize()
    train = np.flatnonzero(dates.isin(boundaries.train_dates).to_numpy())
    validation = np.flatnonzero(dates.isin(boundaries.validation_dates).to_numpy())
    test = np.flatnonzero(dates.isin(boundaries.test_dates).to_numpy())
    if len(train) == 0 or len(test) == 0:
        raise ValueError("El split temporal no produjo filas de train o test.")
    return SplitIndices(
        train=train,
        validation=validation,
        test=test,
        strategy="temporal",
        seed=split.random_state,
    )


def temporal_split(df: pd.DataFrame, config: RunConfig) -> SplitIndices:
    return split_from_boundaries(df, temporal_boundaries(df, config), config)


def expanding_window_folds(
    df: pd.DataFrame,
    config: RunConfig,
    n_splits: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    split = config.split
    date_column = split.group_column or config.data.date_column
    dates = _dates(df, date_column)
    total = len(dates)
    n_splits = max(2, int(n_splits))
    fold_size = max(1, total // (n_splits + 1))
    gap = max(0, int(split.gap_days))
    date_values = pd.to_datetime(df[date_column], errors="coerce").dt.normalize()
    folds: list[tuple[np.ndarray, np.ndarray]] = []
    for fold in range(1, n_splits + 1):
        validation_start = fold * fold_size
        validation_end = min(total, (fold + 1) * fold_size) if fold < n_splits else total
        train_end = max(0, validation_start - gap)
        if train_end == 0 or validation_start >= total:
            continue
        train_dates = dates[:train_end]
        validation_dates = dates[validation_start:validation_end]
        if len(train_dates) == 0 or len(validation_dates) == 0:
            continue
        train_idx = np.flatnonzero(date_values.isin(train_dates).to_numpy())
        validation_idx = np.flatnonzero(date_values.isin(validation_dates).to_numpy())
        if len(train_idx) and len(validation_idx):
            folds.append((train_idx, validation_idx))
    if not folds:
        raise ValueError("No se pudieron construir folds temporales para el tuning.")
    return folds


def split_dataset(df: pd.DataFrame, config: RunConfig) -> SplitIndices:
    split = config.split
    if split.strategy == "temporal":
        return temporal_split(df, config)
    group_column = split.group_column or config.data.group_column
    stratify_column = config.targets.n_ciclos_column
    required_classes = set(config.targets.n_ciclos_classes)

    if split.strategy == "group_shuffle" and group_column in df.columns:
        for seed in range(split.random_state, split.random_state + 100):
            result = _try_group_split(
                df=df,
                group_column=group_column,
                stratify_column=stratify_column,
                test_size=split.test_size,
                validation_size=split.validation_size,
                seed=seed,
                required_classes=required_classes,
            )
            if result is not None:
                return result
        return _fallback_random_split(
            df,
            stratify_column,
            split.test_size,
            split.validation_size,
            split.random_state,
        )

    return _fallback_random_split(
        df,
        stratify_column,
        split.test_size,
        split.validation_size,
        split.random_state,
    )
