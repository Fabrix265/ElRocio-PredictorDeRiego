from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    cohen_kappa_score,
    confusion_matrix,
    f1_score,
)


def _as_float_arrays(y_true: Any, y_pred: Any) -> tuple[np.ndarray, np.ndarray]:
    true = np.asarray(y_true, dtype=float).reshape(-1)
    pred = np.asarray(y_pred, dtype=float).reshape(-1)
    if true.shape != pred.shape:
        raise ValueError(
            f"y_true y y_pred tienen formas distintas: {true.shape} vs {pred.shape}"
        )
    mask = np.isfinite(true) & np.isfinite(pred)
    return true[mask], pred[mask]


def regression_metrics(y_true: Any, y_pred: Any) -> dict[str, float | int]:
    true, pred = _as_float_arrays(y_true, y_pred)
    n = int(true.size)
    if n == 0:
        keys = [
            "n",
            "rmse",
            "mae",
            "r2",
            "mbe",
            "pearson_r",
            "kge",
            "nse",
            "pbias",
            "smape",
            "willmott_d",
            "medae",
            "max_error",
        ]
        return {key: (0 if key == "n" else np.nan) for key in keys}

    error = pred - true
    sse = float(np.sum(error**2))
    mean_true = float(np.mean(true))
    mean_pred = float(np.mean(pred))
    sst = float(np.sum((true - mean_true) ** 2))

    rmse = float(np.sqrt(np.mean(error**2)))
    mae = float(np.mean(np.abs(error)))
    medae = float(np.median(np.abs(error)))
    max_error = float(np.max(np.abs(error)))
    mbe = float(np.mean(error))
    r2 = float(1.0 - sse / sst) if sst > 0 else np.nan
    nse = r2

    if n >= 2 and np.std(true) > 0 and np.std(pred) > 0:
        pearson_r = float(np.corrcoef(true, pred)[0, 1])
    else:
        pearson_r = np.nan

    if (
        np.isfinite(pearson_r)
        and np.std(true) > 0
        and mean_true != 0
        and np.std(pred) > 0
    ):
        alpha = float(np.std(pred) / np.std(true))
        beta = float(mean_pred / mean_true)
        kge = float(1.0 - np.sqrt((pearson_r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2))
    else:
        kge = np.nan

    pbias = float(100.0 * np.sum(error) / np.sum(true)) if np.sum(true) != 0 else np.nan

    denominator = np.abs(true) + np.abs(pred)
    smape_terms = np.where(denominator == 0, 0.0, 2.0 * np.abs(error) / denominator)
    smape = float(100.0 * np.mean(smape_terms))

    d_denominator = float(
        np.sum((np.abs(pred - mean_true) + np.abs(true - mean_true)) ** 2)
    )
    willmott_d = float(1.0 - sse / d_denominator) if d_denominator > 0 else np.nan

    return {
        "n": n,
        "rmse": rmse,
        "mae": mae,
        "r2": r2,
        "mbe": mbe,
        "pearson_r": pearson_r,
        "kge": kge,
        "nse": nse,
        "pbias": pbias,
        "smape": smape,
        "willmott_d": willmott_d,
        "medae": medae,
        "max_error": max_error,
    }


def classification_metrics(
    y_true: Any, y_pred: Any, labels: list[int] | None = None
) -> dict[str, Any]:
    true = np.asarray(y_true).reshape(-1)
    pred = np.asarray(y_pred).reshape(-1)
    mask = np.isfinite(true.astype(float)) & np.isfinite(pred.astype(float))
    true = true[mask].astype(int)
    pred = pred[mask].astype(int)
    if true.size == 0:
        return {
            "n": 0,
            "accuracy": np.nan,
            "balanced_accuracy": np.nan,
            "f1_macro": np.nan,
            "cohen_kappa": np.nan,
            "confusion_matrix": [],
            "labels": labels or [],
        }

    if labels is None:
        labels = sorted(set(true.tolist()) | set(pred.tolist()))
    labels = [int(label) for label in labels]

    cm = confusion_matrix(true, pred, labels=labels)
    return {
        "n": int(true.size),
        "accuracy": float(accuracy_score(true, pred)),
        "balanced_accuracy": float(balanced_accuracy_score(true, pred)),
        "f1_macro": float(f1_score(true, pred, average="macro", zero_division=0)),
        "cohen_kappa": float(cohen_kappa_score(true, pred)),
        "confusion_matrix": cm.tolist(),
        "labels": labels,
    }
