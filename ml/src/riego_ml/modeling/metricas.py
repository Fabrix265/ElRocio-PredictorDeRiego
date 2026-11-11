"""Métricas de regresión (hidrológicas incluidas) y de clasificación."""

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


def regresion(y_true: Any, y_pred: Any) -> dict[str, float]:
    obs = np.asarray(y_true, dtype=float).ravel()
    sim = np.asarray(y_pred, dtype=float).ravel()
    ok = np.isfinite(obs) & np.isfinite(sim)
    obs, sim = obs[ok], sim[ok]
    n = int(obs.size)
    if n < 2:
        return {"n": n}
    err = sim - obs
    sse = float(np.sum(err**2))
    sst = float(np.sum((obs - obs.mean()) ** 2))
    r = float(np.corrcoef(obs, sim)[0, 1]) if obs.std() > 0 and sim.std() > 0 else np.nan
    alpha = sim.std() / obs.std() if obs.std() > 0 else np.nan
    beta = sim.mean() / obs.mean() if obs.mean() != 0 else np.nan
    kge = 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2) if np.isfinite(r) else np.nan
    d_den = float(np.sum((np.abs(sim - obs.mean()) + np.abs(obs - obs.mean())) ** 2))
    return {
        "n": n,
        "rmse": float(np.sqrt(sse / n)),
        "mae": float(np.mean(np.abs(err))),
        "r2": 1 - sse / sst if sst > 0 else np.nan,
        "mbe": float(err.mean()),
        "pearson_r": r,
        "kge": float(kge),
        "pbias_pct": float(100 * err.sum() / obs.sum()) if obs.sum() != 0 else np.nan,
        "willmott_d": 1 - sse / d_den if d_den > 0 else np.nan,
        "medae": float(np.median(np.abs(err))),
    }


def clasificacion(y_true: Any, y_pred: Any, etiquetas: list[int]) -> dict[str, Any]:
    obs = np.asarray(y_true).astype(int).ravel()
    sim = np.asarray(y_pred).astype(int).ravel()
    if obs.size == 0:
        return {"n": 0}
    return {
        "n": int(obs.size),
        "accuracy": float(accuracy_score(obs, sim)),
        "accuracy_pm1": float(np.mean(np.abs(obs - sim) <= 1)),
        "balanced_accuracy": float(balanced_accuracy_score(obs, sim)),
        "f1_macro": float(f1_score(obs, sim, average="macro", labels=etiquetas, zero_division=0)),
        "cohen_kappa": float(cohen_kappa_score(obs, sim)),
        "mae_ciclos": float(np.mean(np.abs(obs - sim))),
        "confusion": confusion_matrix(obs, sim, labels=etiquetas).tolist(),
    }
