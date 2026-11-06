from __future__ import annotations

from dataclasses import dataclass
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


def split_dataset(df: pd.DataFrame, config: RunConfig) -> SplitIndices:
    split = config.split
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
