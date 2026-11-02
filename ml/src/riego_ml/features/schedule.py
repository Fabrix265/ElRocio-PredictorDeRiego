from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from riego_ml.config.schema import RunConfig
from riego_ml.preprocessing.cleaning import minutes_to_hhmm


def _prediction_column(slot: int, kind: str) -> str:
    if kind == "m3":
        return f"Riego_ciclo_{slot}_pred_m3"
    if kind == "start":
        return f"Hora_inicio_{slot}_pred_min"
    if kind == "duration":
        return f"Tiempo_ciclo_{slot}_pred_min"
    return f"Hora_fin_{slot}_pred_min"


def _actual_column(slot: int, kind: str) -> str:
    if kind == "m3":
        return f"Riego_ciclo_{slot}_m3"
    if kind == "start":
        return f"Hora_inicio_{slot}_min"
    if kind == "duration":
        return f"Tiempo_ciclo_{slot}_min"
    return f"Hora_fin_{slot}_min"


def _clean_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce").replace([np.inf, -np.inf], np.nan)


def build_prediction_frame(
    turno_df: pd.DataFrame,
    indices: np.ndarray,
    predictions: dict[str, np.ndarray],
    config: RunConfig,
    model_name: str,
    split: str,
) -> pd.DataFrame:
    base = turno_df.iloc[indices].reset_index(drop=True)
    max_cycles = config.data.max_cycles
    id_columns = [c for c in config.data.id_columns if c in base.columns]

    frame = base[id_columns].copy()
    frame.insert(0, "modelo", model_name)
    frame.insert(1, "split", split)
    frame["N_ciclos_real"] = pd.to_numeric(
        base[config.targets.n_ciclos_column], errors="coerce"
    ).round()
    frame["Riego_total_real_m3"] = _clean_numeric(base[config.targets.total_column])

    raw_n = np.asarray(predictions.get("n_ciclos", np.full(len(base), np.nan)))
    n_ciclos = pd.Series(raw_n, index=frame.index)
    n_ciclos = pd.to_numeric(n_ciclos, errors="coerce").fillna(1).round().astype(int)
    n_ciclos = n_ciclos.clip(1, max_cycles)
    frame["N_ciclos_pred"] = n_ciclos.to_numpy()

    for slot in range(1, max_cycles + 1):
        active = frame["N_ciclos_pred"] >= slot

        m3 = _clean_numeric(
            pd.Series(
                predictions.get(f"Riego_ciclo_{slot}_m3", np.full(len(base), np.nan)),
                index=frame.index,
            )
        ).clip(lower=0)
        start = _clean_numeric(
            pd.Series(
                predictions.get(f"Hora_inicio_{slot}_min", np.full(len(base), np.nan)),
                index=frame.index,
            )
        ).clip(lower=0, upper=24 * 60)
        duration = _clean_numeric(
            pd.Series(
                predictions.get(f"Tiempo_ciclo_{slot}_min", np.full(len(base), np.nan)),
                index=frame.index,
            )
        ).clip(lower=0, upper=24 * 60)

        frame[f"Riego_ciclo_{slot}_pred_m3"] = m3.where(active)
        frame[f"Hora_inicio_{slot}_pred_min"] = start.where(active)
        frame[f"Tiempo_ciclo_{slot}_pred_min"] = duration.where(active)

    frame = postprocess_schedule(frame, max_cycles, config.schedule.min_gap_min)

    frame["Riego_total_pred_m3"] = 0.0
    for slot in range(1, max_cycles + 1):
        frame["Riego_total_pred_m3"] += frame[f"Riego_ciclo_{slot}_pred_m3"].fillna(0)
        for kind in ("m3", "start", "duration", "end"):
            pred_col = _prediction_column(slot, kind)
            actual_col = _actual_column(slot, kind)
            if actual_col in base.columns:
                frame[actual_col] = base[actual_col]
            if kind == "m3":
                continue
            frame[f"{pred_col}_hhmm"] = frame[pred_col].map(minutes_to_hhmm)
            if actual_col in base.columns:
                frame[f"{actual_col}_hhmm"] = base[actual_col].map(minutes_to_hhmm)

    frame["orden_valido"] = frame["ajustes_horario"] == 0
    return frame


def postprocess_schedule(
    frame: pd.DataFrame, max_cycles: int, min_gap_min: float = 0.0
) -> pd.DataFrame:
    result = frame.copy()
    result["ajustes_horario"] = 0
    for index, row in result.iterrows():
        previous_end = np.nan
        for slot in range(1, max_cycles + 1):
            start_col = f"Hora_inicio_{slot}_pred_min"
            duration_col = f"Tiempo_ciclo_{slot}_pred_min"
            end_col = f"Hora_fin_{slot}_pred_min"
            start = row.get(start_col)
            duration = row.get(duration_col)
            if pd.isna(start) or pd.isna(duration):
                result.at[index, end_col] = np.nan
                continue
            start = float(start)
            duration = float(duration)
            if pd.notna(previous_end):
                minimum_start = float(previous_end) + max(0.0, float(min_gap_min))
                if start < minimum_start:
                    start = minimum_start
                    result.at[index, "ajustes_horario"] += 1
            end = start + duration
            result.at[index, start_col] = start
            result.at[index, end_col] = end
            previous_end = end
    return result


def _is_schedule_valid(row: pd.Series, max_cycles: int) -> bool:
    intervals: list[tuple[float, float]] = []
    for slot in range(1, max_cycles + 1):
        start = row.get(f"Hora_inicio_{slot}_pred_min")
        end = row.get(f"Hora_fin_{slot}_pred_min")
        if pd.isna(start) or pd.isna(end):
            continue
        intervals.append((float(start), float(end)))
    for (_, previous_end), (next_start, _) in zip(intervals, intervals[1:]):
        if next_start < previous_end:
            return False
    return True


def actual_schedule_frame(
    turno_df: pd.DataFrame, indices: np.ndarray, config: RunConfig
) -> pd.DataFrame:
    base = turno_df.iloc[indices].reset_index(drop=True)
    id_columns = [c for c in config.data.id_columns if c in base.columns]
    frame = base[id_columns].copy()
    frame["N_ciclos_real"] = base[config.targets.n_ciclos_column]
    for slot in range(1, config.data.max_cycles + 1):
        for kind in ("m3", "start", "duration", "end"):
            actual_col = _actual_column(slot, kind)
            if actual_col in base.columns:
                frame[actual_col] = base[actual_col]
                frame[f"{actual_col}_hhmm"] = base[actual_col].map(minutes_to_hhmm)
    return frame


def _column_or_nan(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in frame.columns:
        return pd.to_numeric(frame[column], errors="coerce").replace(
            [np.inf, -np.inf], np.nan
        )
    return pd.Series(np.nan, index=frame.index, dtype=float)


def schedule_metrics(frame: pd.DataFrame, max_cycles: int) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    for slot in range(1, max_cycles + 1):
        for kind in ("start", "duration", "end"):
            actual = _column_or_nan(frame, _actual_column(slot, kind))
            predicted = _column_or_nan(frame, _prediction_column(slot, kind))
            mask = actual.notna() & predicted.notna()
            if mask.sum() == 0:
                metrics[f"slot_{slot}_{kind}_mae"] = np.nan
                metrics[f"slot_{slot}_{kind}_rmse"] = np.nan
                continue
            error = predicted[mask] - actual[mask]
            metrics[f"slot_{slot}_{kind}_mae"] = float(np.mean(np.abs(error)))
            metrics[f"slot_{slot}_{kind}_rmse"] = float(np.sqrt(np.mean(error**2)))
    if "orden_valido" in frame.columns:
        metrics["orden_valido_pct"] = float(frame["orden_valido"].mean() * 100)
    else:
        metrics["orden_valido_pct"] = np.nan
    return metrics
