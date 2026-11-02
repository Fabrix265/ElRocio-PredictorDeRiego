from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from riego_ml.evaluation.metrics import regression_metrics


def _save(fig: plt.Figure, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(target, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return target


def _placeholder(path: str | Path, message: str) -> Path:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.text(0.5, 0.5, message, ha="center", va="center", wrap=True)
    ax.axis("off")
    return _save(fig, path)


def _finite_pairs(y_true: Any, y_pred: Any) -> tuple[np.ndarray, np.ndarray]:
    true = np.asarray(y_true, dtype=float).reshape(-1)
    pred = np.asarray(y_pred, dtype=float).reshape(-1)
    mask = np.isfinite(true) & np.isfinite(pred)
    return true[mask], pred[mask]


def plot_pred_vs_obs(
    y_true: Any, y_pred: Any, title: str, path: str | Path, unit: str = ""
) -> Path:
    true, pred = _finite_pairs(y_true, y_pred)
    if true.size == 0:
        return _placeholder(path, "Sin datos válidos")
    fig, ax = plt.subplots(figsize=(6, 5))
    ax.scatter(true, pred, alpha=0.65, edgecolor="k", linewidth=0.3)
    low = float(min(true.min(), pred.min()))
    high = float(max(true.max(), pred.max()))
    ax.plot([low, high], [low, high], color="crimson", linestyle="--", label="1:1")
    metrics = regression_metrics(true, pred)
    ax.set_xlabel(f"Observado {unit}".strip())
    ax.set_ylabel(f"Predicho {unit}".strip())
    ax.set_title(title)
    ax.legend(loc="best")
    ax.text(
        0.02,
        0.98,
        f"RMSE={metrics['rmse']:.2f}\nR²={metrics['r2']:.3f}\nMAE={metrics['mae']:.2f}",
        transform=ax.transAxes,
        va="top",
        fontsize=8,
        bbox={"boxstyle": "round", "facecolor": "white", "alpha": 0.8},
    )
    return _save(fig, path)


def plot_residuals(
    y_true: Any, y_pred: Any, title: str, path: str | Path
) -> Path:
    true, pred = _finite_pairs(y_true, y_pred)
    if true.size == 0:
        return _placeholder(path, "Sin datos válidos")
    residual = pred - true
    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.scatter(pred, residual, alpha=0.65, edgecolor="k", linewidth=0.3)
    ax.axhline(0, color="crimson", linestyle="--")
    ax.set_xlabel("Predicho")
    ax.set_ylabel("Residual (predicho - observado)")
    ax.set_title(title)
    return _save(fig, path)


def plot_residual_hist(
    y_true: Any, y_pred: Any, title: str, path: str | Path
) -> Path:
    true, pred = _finite_pairs(y_true, y_pred)
    if true.size == 0:
        return _placeholder(path, "Sin datos válidos")
    residual = pred - true
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(residual, bins=min(30, max(5, int(np.sqrt(residual.size)))), edgecolor="k", alpha=0.75)
    ax.axvline(0, color="crimson", linestyle="--")
    ax.set_xlabel("Residual")
    ax.set_ylabel("Frecuencia")
    ax.set_title(title)
    return _save(fig, path)


def plot_time_series(
    frame: pd.DataFrame,
    actual_column: str,
    predicted_column: str,
    title: str,
    path: str | Path,
    max_points: int = 120,
) -> Path:
    if actual_column not in frame.columns or predicted_column not in frame.columns:
        return _placeholder(path, "Sin columnas para serie temporal")
    data = frame.copy()
    if "Fecha" in data.columns:
        data["_fecha"] = pd.to_datetime(data["Fecha"], errors="coerce")
        sort_columns = ["_fecha"] + [c for c in ["Modulo", "Turno"] if c in data.columns]
        data = data.sort_values(sort_columns)
    data = data.head(max_points)
    labels = []
    for _, row in data.iterrows():
        date = row.get("Fecha", "")
        turno = row.get("Turno", "")
        labels.append(f"{date} {turno}".strip())
    x = np.arange(len(data))
    fig, ax = plt.subplots(figsize=(max(8, len(data) * 0.12), 4.5))
    ax.plot(x, pd.to_numeric(data[actual_column], errors="coerce"), marker="o", label="Observado")
    ax.plot(x, pd.to_numeric(data[predicted_column], errors="coerce"), marker="s", label="Predicho")
    step = max(1, len(labels) // 12)
    ax.set_xticks(x[::step])
    ax.set_xticklabels(labels[::step], rotation=45, ha="right", fontsize=7)
    ax.set_ylabel("Valor")
    ax.set_title(title)
    ax.legend()
    return _save(fig, path)


def _history_series(history: Any) -> tuple[list[float], list[float], str]:
    if not history:
        return [], [], ""
    if isinstance(history, dict) and {"iteration", "value"}.issubset(history.keys()):
        return list(history["iteration"]), list(history["value"]), str(history.get("metric", [""])[0] if history.get("metric") else "")
    if isinstance(history, dict):
        for _, values in history.items():
            if isinstance(values, dict):
                for metric_name, series in values.items():
                    if isinstance(series, list) and series:
                        return list(range(1, len(series) + 1)), list(series), metric_name
    return [], [], ""


def plot_early_stopping(history: Any, title: str, path: str | Path) -> Path:
    iterations, values, metric = _history_series(history)
    if not iterations:
        return _placeholder(path, "Sin historial de early stopping")
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.plot(iterations, values, marker="o")
    best_index = int(np.nanargmin(np.asarray(values, dtype=float)))
    ax.scatter([iterations[best_index]], [values[best_index]], color="crimson", zorder=3, label="Mejor")
    ax.set_xlabel("Iteración / árboles / época")
    ax.set_ylabel(metric or "Métrica")
    ax.set_title(title)
    ax.legend()
    return _save(fig, path)


def plot_feature_importance(
    importance: pd.Series, title: str, path: str | Path, top_n: int = 20
) -> Path:
    if importance is None or importance.empty:
        return _placeholder(path, "El modelo no expone importancia de features")
    data = importance.head(top_n).sort_values()
    fig, ax = plt.subplots(figsize=(7, max(4, len(data) * 0.28)))
    ax.barh(data.index, data.values, color="#2f6f8f")
    ax.set_xlabel("Importancia")
    ax.set_title(title)
    return _save(fig, path)


def plot_confusion_matrix(
    cm: list[list[int]], labels: list[int], title: str, path: str | Path
) -> Path:
    matrix = np.asarray(cm, dtype=float)
    if matrix.size == 0:
        return _placeholder(path, "Sin matriz de confusión")
    fig, ax = plt.subplots(figsize=(5.5, 4.5))
    image = ax.imshow(matrix, cmap="Blues")
    fig.colorbar(image, ax=ax, fraction=0.046, pad=0.04)
    ax.set_xticks(np.arange(len(labels)))
    ax.set_yticks(np.arange(len(labels)))
    ax.set_xticklabels(labels)
    ax.set_yticklabels(labels)
    ax.set_xlabel("Predicho")
    ax.set_ylabel("Observado")
    ax.set_title(title)
    for i in range(matrix.shape[0]):
        for j in range(matrix.shape[1]):
            ax.text(j, i, int(matrix[i, j]), ha="center", va="center", color="black")
    return _save(fig, path)


def plot_class_distribution(
    y_true: Any, y_pred: Any, labels: list[int], title: str, path: str | Path
) -> Path:
    true = pd.Series(np.asarray(y_true).reshape(-1)).dropna().astype(int)
    pred = pd.Series(np.asarray(y_pred).reshape(-1)).dropna().astype(int)
    if true.empty and pred.empty:
        return _placeholder(path, "Sin datos de clases")
    x = np.arange(len(labels))
    width = 0.38
    true_counts = [int((true == label).sum()) for label in labels]
    pred_counts = [int((pred == label).sum()) for label in labels]
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(x - width / 2, true_counts, width, label="Observado")
    ax.bar(x + width / 2, pred_counts, width, label="Predicho")
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Cantidad de turnos")
    ax.set_title(title)
    ax.legend()
    return _save(fig, path)


def plot_schedule_gantt(
    actual: pd.DataFrame,
    predicted: pd.DataFrame,
    max_cycles: int,
    title: str,
    path: str | Path,
    max_turnos: int = 6,
) -> Path:
    if actual.empty or predicted.empty:
        return _placeholder(path, "Sin horarios para graficar")
    actual = actual.head(max_turnos).reset_index(drop=True)
    predicted = predicted.head(max_turnos).reset_index(drop=True)
    n = min(len(actual), len(predicted))
    if n == 0:
        return _placeholder(path, "Sin horarios para graficar")

    fig, axes = plt.subplots(n, 1, figsize=(9, max(3, 1.4 * n)), sharex=True)
    if n == 1:
        axes = [axes]
    colors = ["#2f6f8f", "#4f9f6f", "#c98b2f"]
    for row_index in range(n):
        ax = axes[row_index]
        for slot in range(1, max_cycles + 1):
            actual_start = actual.loc[row_index, f"Hora_inicio_{slot}_min"]
            actual_end = actual.loc[row_index, f"Hora_fin_{slot}_min"]
            pred_start = predicted.loc[row_index, f"Hora_inicio_{slot}_pred_min"]
            pred_end = predicted.loc[row_index, f"Hora_fin_{slot}_pred_min"]
            if pd.notna(actual_start) and pd.notna(actual_end):
                ax.broken_barh(
                    [(float(actual_start), float(actual_end - actual_start))],
                    (0.55, 0.35),
                    facecolors=colors[(slot - 1) % len(colors)],
                    alpha=0.65,
                )
            if pd.notna(pred_start) and pd.notna(pred_end):
                ax.broken_barh(
                    [(float(pred_start), float(pred_end - pred_start))],
                    (0.10, 0.35),
                    facecolors=colors[(slot - 1) % len(colors)],
                    alpha=1.0,
                )
        label = f"{actual.loc[row_index, 'Fecha']} {actual.loc[row_index, 'Turno']}"
        ax.set_yticks([0.27, 0.72])
        ax.set_yticklabels(["Predicho", "Observado"], fontsize=7)
        ax.set_ylabel(label, rotation=0, ha="right", va="center", fontsize=7)
        ax.grid(axis="x", alpha=0.25)
    axes[-1].set_xlabel("Minutos desde medianoche")
    axes[-1].set_xlim(0, 24 * 60)
    fig.suptitle(title)
    return _save(fig, path)


def plot_metric_by_slot(
    metrics: dict[str, Any], metric_name: str, title: str, path: str | Path
) -> Path:
    slots = []
    values = []
    for key, value in metrics.items():
        if key.startswith("slot_") and key.endswith(f"_{metric_name}"):
            parts = key.split("_")
            slots.append(int(parts[1]))
            values.append(value)
    if not slots:
        return _placeholder(path, "Sin métricas por ciclo")
    order = np.argsort(slots)
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.bar(np.asarray(slots)[order], np.asarray(values, dtype=float)[order], color="#2f6f8f")
    ax.set_xlabel("Ciclo")
    ax.set_ylabel(metric_name.upper())
    ax.set_title(title)
    ax.set_xticks(np.asarray(slots)[order])
    return _save(fig, path)


def plot_model_comparison(
    metrics_df: pd.DataFrame,
    metric: str,
    title: str,
    path: str | Path,
) -> Path:
    if metrics_df.empty or metric not in metrics_df.columns:
        return _placeholder(path, f"Sin métricas '{metric}'")
    data = metrics_df.dropna(subset=[metric])
    if data.empty:
        return _placeholder(path, f"Sin métricas '{metric}'")
    pivot = data.pivot_table(index="target", columns="model", values=metric, aggfunc="mean")
    if pivot.empty:
        return _placeholder(path, f"Sin métricas '{metric}'")
    fig, ax = plt.subplots(figsize=(max(8, len(pivot) * 1.1), 4.8))
    pivot.plot(kind="bar", ax=ax)
    ax.set_ylabel(metric.upper())
    ax.set_title(title)
    ax.legend(title="Modelo", fontsize=7)
    ax.grid(axis="y", alpha=0.25)
    return _save(fig, path)
