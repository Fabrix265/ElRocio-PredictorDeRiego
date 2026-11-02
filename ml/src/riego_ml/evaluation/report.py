from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _write_sheet(
    writer: pd.ExcelWriter,
    name: str,
    frame: pd.DataFrame,
    freeze: str = "A2",
) -> None:
    sheet_name = name[:31]
    if frame is None or frame.empty:
        pd.DataFrame({"Mensaje": ["Sin datos"]}).to_excel(
            writer, sheet_name=sheet_name, index=False
        )
        return
    frame.to_excel(writer, sheet_name=sheet_name, index=False)
    worksheet = writer.sheets[sheet_name]
    worksheet.freeze_panes = freeze
    worksheet.autofilter(0, 0, len(frame), max(0, len(frame.columns) - 1))
    header_format = writer.book.add_format(
        {"bold": True, "bg_color": "#D9EAF7", "border": 1}
    )
    for column_index, column in enumerate(frame.columns):
        worksheet.write(0, column_index, column, header_format)
        values = frame[column].astype(str)
        max_length = max(len(str(column)), int(values.str.len().max()) if len(values) else 0)
        worksheet.set_column(column_index, column_index, min(max(10, max_length + 2), 45))


def _long_predictions(prediction_frames: list[pd.DataFrame], max_cycles: int) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for frame in prediction_frames:
        if frame.empty:
            continue
        id_columns = [
            column
            for column in ["modelo", "split", "Fecha", "Fundo", "Modulo", "Turno"]
            if column in frame.columns
        ]
        for slot in range(1, max_cycles + 1):
            columns = {
                "ciclo": slot,
                "Riego_ciclo_real_m3": f"Riego_ciclo_{slot}_m3",
                "Riego_ciclo_pred_m3": f"Riego_ciclo_{slot}_pred_m3",
                "Hora_inicio_real_min": f"Hora_inicio_{slot}_min",
                "Hora_inicio_pred_min": f"Hora_inicio_{slot}_pred_min",
                "Hora_fin_real_min": f"Hora_fin_{slot}_min",
                "Hora_fin_pred_min": f"Hora_fin_{slot}_pred_min",
                "Tiempo_ciclo_real_min": f"Tiempo_ciclo_{slot}_min",
                "Tiempo_ciclo_pred_min": f"Tiempo_ciclo_{slot}_pred_min",
                "Hora_inicio_real": f"Hora_inicio_{slot}_min_hhmm",
                "Hora_inicio_pred": f"Hora_inicio_{slot}_pred_min_hhmm",
                "Hora_fin_real": f"Hora_fin_{slot}_min_hhmm",
                "Hora_fin_pred": f"Hora_fin_{slot}_pred_min_hhmm",
            }
            piece = frame[id_columns].copy()
            piece["ciclo"] = slot
            for output_column, source_column in columns.items():
                if output_column == "ciclo":
                    continue
                piece[output_column] = frame[source_column] if source_column in frame.columns else np.nan
            rows.append(piece)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _confusion_rows(
    classification_rows: list[dict[str, Any]],
    prediction_frames: list[pd.DataFrame],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for row in classification_rows:
        labels = row.get("labels") or []
        matrix = row.get("confusion_matrix") or []
        for i, true_label in enumerate(labels):
            for j, pred_label in enumerate(labels):
                count = int(matrix[i][j]) if i < len(matrix) and j < len(matrix[i]) else 0
                rows.append(
                    {
                        "modelo": row["model"],
                        "split": row.get("split", "test"),
                        "clase_real": true_label,
                        "clase_predicha": pred_label,
                        "conteo": count,
                    }
                )
    return pd.DataFrame(rows)


def _ranking(regression_df: pd.DataFrame, classification_df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    if not regression_df.empty:
        for target, group in regression_df.groupby("target"):
            if "rmse" not in group.columns:
                continue
            for _, row in group.sort_values("rmse").iterrows():
                rows.append(
                    {
                        "tipo": "regresion",
                        "target": target,
                        "modelo": row["model"],
                        "metrica_principal": "rmse",
                        "valor": row.get("rmse"),
                        "mae": row.get("mae"),
                        "r2": row.get("r2"),
                    }
                )
    if not classification_df.empty:
        for _, row in classification_df.sort_values("f1_macro", ascending=False).iterrows():
            rows.append(
                {
                    "tipo": "clasificacion",
                    "target": row.get("target", "n_ciclos"),
                    "modelo": row["model"],
                    "metrica_principal": "f1_macro",
                    "valor": row.get("f1_macro"),
                    "mae": np.nan,
                    "r2": np.nan,
                }
            )
    return pd.DataFrame(rows)


def _config_frame(config_rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(config_rows)


def _model_frame(model_rows: list[dict[str, Any]]) -> pd.DataFrame:
    frame = pd.DataFrame(model_rows)
    for column in ("params", "early_stopping"):
        if column in frame.columns:
            frame[column] = frame[column].map(_json_text)
    return frame


def write_excel_report(
    path: str | Path,
    regression_rows: list[dict[str, Any]],
    classification_rows: list[dict[str, Any]],
    schedule_rows: list[dict[str, Any]],
    prediction_frames: list[pd.DataFrame],
    errors_frames: list[pd.DataFrame],
    group_rows: list[dict[str, Any]],
    config_rows: list[dict[str, Any]],
    model_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    max_cycles: int,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    regression_df = pd.DataFrame(regression_rows)
    classification_df = pd.DataFrame(classification_rows)
    schedule_df = pd.DataFrame(schedule_rows)
    predictions_df = pd.concat(prediction_frames, ignore_index=True) if prediction_frames else pd.DataFrame()
    long_predictions = _long_predictions(prediction_frames, max_cycles)
    confusion_df = _confusion_rows(classification_rows, prediction_frames)
    errors_df = pd.concat(errors_frames, ignore_index=True) if errors_frames else pd.DataFrame()
    group_df = pd.DataFrame(group_rows)
    ranking_df = _ranking(regression_df, classification_df)
    config_df = _config_frame(config_rows)
    model_df = _model_frame(model_rows)
    targets_df = pd.DataFrame(target_rows)

    for frame in (regression_df, classification_df, schedule_df, group_df):
        if not frame.empty:
            numeric_columns = frame.select_dtypes(include=[np.number]).columns
            frame[numeric_columns] = frame[numeric_columns].round(4)

    with pd.ExcelWriter(target, engine="xlsxwriter") as writer:
        _write_sheet(writer, "Resumen_Regresion", regression_df)
        _write_sheet(writer, "Resumen_Clasificacion", classification_df.drop(columns=["confusion_matrix", "labels"], errors="ignore"))
        _write_sheet(writer, "Horarios", schedule_df)
        _write_sheet(writer, "Ranking", ranking_df)
        _write_sheet(writer, "Predicciones_Turno", predictions_df)
        _write_sheet(writer, "Predicciones_Ciclo", long_predictions)
        _write_sheet(writer, "Confusion_N_Ciclos", confusion_df)
        _write_sheet(writer, "Errores_Top", errors_df)
        _write_sheet(writer, "Metricas_Grupo", group_df)
        _write_sheet(writer, "Targets", targets_df)
        _write_sheet(writer, "Modelos", model_df)
        _write_sheet(writer, "Configuracion", config_df)

    return target
