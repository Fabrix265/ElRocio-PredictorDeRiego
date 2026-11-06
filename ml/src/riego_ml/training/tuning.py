from __future__ import annotations

import warnings
from typing import Any

import numpy as np
import pandas as pd
from sklearn.model_selection import RandomizedSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder

from riego_ml.config.schema import ModelConfig, TuningConfig
from riego_ml.features.build import build_preprocessor
from riego_ml.features.targets import TargetSpec
from riego_ml.training.registry import build_model, resolve_model_name


PARAM_SPACES: dict[str, dict[str, list[Any]]] = {
    "random_forest": {
        "n_estimators": [100, 200, 300, 500],
        "max_depth": [None, 4, 6, 8, 12, 16],
        "min_samples_leaf": [1, 2, 4, 8],
        "min_samples_split": [2, 4, 8],
        "max_features": ["sqrt", "log2", None],
    },
    "xgboost": {
        "n_estimators": [200, 300, 500, 800],
        "max_depth": [3, 4, 5, 6, 8],
        "learning_rate": [0.01, 0.03, 0.05, 0.1],
        "subsample": [0.7, 0.8, 0.9, 1.0],
        "colsample_bytree": [0.7, 0.8, 0.9, 1.0],
        "reg_lambda": [0.0, 0.1, 1.0, 5.0, 10.0],
        "min_child_weight": [1, 3, 5],
    },
    "svr": {
        "C": [0.1, 1.0, 10.0, 100.0],
        "epsilon": [0.01, 0.1, 0.5, 1.0],
        "kernel": ["rbf", "linear"],
        "gamma": ["scale", "auto"],
    },
    "mlp": {
        "hidden_layer_sizes": [(32,), (64,), (64, 32), (128, 64), (32, 16)],
        "alpha": [1e-5, 1e-4, 1e-3, 1e-2],
        "learning_rate_init": [1e-3, 5e-3, 1e-2],
        "batch_size": [32, 64, 128],
    },
}


def _space_size(space: dict[str, list[Any]]) -> int:
    return int(np.prod([len(values) for values in space.values()]))


def tune_params(
    model_name: str,
    model_config: ModelConfig,
    X: pd.DataFrame,
    y: pd.Series,
    spec: TargetSpec,
    folds: list[tuple[np.ndarray, np.ndarray]],
    categorical_features: list[str],
    numeric_features: list[str],
    tuning: TuningConfig,
    random_state: int,
) -> dict[str, Any]:
    resolved = resolve_model_name(model_name)
    if resolved not in PARAM_SPACES:
        raise ValueError(f"No hay espacio de búsqueda para el modelo: {model_name}")

    wrapper = build_model(model_name, model_config, random_state=random_state)
    estimator = (
        wrapper._make_classifier()
        if spec.kind == "classification"
        else wrapper._make_regressor()
    )

    target = y.to_numpy()
    mask = ~pd.isna(target)
    X_fit = X.loc[mask].reset_index(drop=True)
    target = target[mask]
    original_indices = np.flatnonzero(mask)
    adapted_folds = [
        (
            np.intersect1d(train_idx, original_indices),
            np.intersect1d(validation_idx, original_indices),
        )
        for train_idx, validation_idx in folds
    ]
    row_position = {int(index): position for position, index in enumerate(original_indices)}
    cv = [
        (
            np.array([row_position[int(index)] for index in train_idx], dtype=int),
            np.array([row_position[int(index)] for index in validation_idx], dtype=int),
        )
        for train_idx, validation_idx in adapted_folds
    ]
    cv = [(train, validation) for train, validation in cv if len(train) and len(validation)]
    if not cv:
        raise ValueError(f"No hay folds válidos para tunear {model_name}/{spec.name}.")

    if spec.kind == "classification":
        encoder = LabelEncoder()
        target = encoder.fit_transform(target.astype(int))
        scoring = tuning.scoring_classification
    else:
        target = target.astype(float)
        scoring = tuning.scoring_regression

    pipeline = Pipeline(
        [
            (
                "pre",
                build_preprocessor(
                    categorical_features,
                    numeric_features,
                    scale_numeric=wrapper.scale_numeric,
                ),
            ),
            ("model", estimator),
        ]
    )
    space = {
        f"model__{key}": values for key, values in PARAM_SPACES[resolved].items()
    }
    n_iter = min(max(1, tuning.n_iter), _space_size(PARAM_SPACES[resolved]))

    search = RandomizedSearchCV(
        pipeline,
        param_distributions=space,
        n_iter=n_iter,
        scoring=scoring,
        cv=cv,
        random_state=random_state,
        n_jobs=tuning.n_jobs,
        refit=True,
        error_score="raise",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=UserWarning)
        search.fit(X_fit, target)
    best = {
        key.removeprefix("model__"): value for key, value in search.best_params_.items()
    }
    return {
        "params": best,
        "best_score": float(search.best_score_),
        "scoring": scoring,
        "n_iter": n_iter,
    }
