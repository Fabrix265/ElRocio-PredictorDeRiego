from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from riego_ml.config.schema import RunConfig
from riego_ml.data.loader import load_dataset
from riego_ml.data.validation import validate_raw_dataset
from riego_ml.features.aggregate import aggregate_to_turno
from riego_ml.features.schedule import build_prediction_frame
from riego_ml.preprocessing.cleaning import prepare_cycle_data
from riego_ml.training.base import BaseMultiTargetModel
from riego_ml.utils.io import load_json
from riego_ml.utils.logging import configure_logging


class Predictor:
    def __init__(self, config: RunConfig, model_name: str):
        self.config = config
        self.model_name = model_name
        self.logger = configure_logging()
        self.model_dir = Path(config.models_dir) / model_name
        if not self.model_dir.exists():
            raise FileNotFoundError(
                f"No existe el modelo '{model_name}' en {self.model_dir}. Entrena primero."
            )
        self.metadata = load_json(self.model_dir / "metadata.json")
        self.model = BaseMultiTargetModel.load(self.model_dir / "model.joblib")
        self.preprocessor = joblib.load(self.model_dir / "preprocessor.joblib")
        self._validate_metadata()

    def _validate_metadata(self) -> None:
        trained_max_cycles = int(self.metadata.get("data", {}).get("max_cycles", -1))
        if trained_max_cycles != self.config.data.max_cycles:
            raise ValueError(
                "El modelo fue entrenado con max_cycles="
                f"{trained_max_cycles} y la configuración actual usa "
                f"{self.config.data.max_cycles}. Usa la misma configuración."
            )
        trained_group = self.metadata.get("data", {}).get("group_column")
        if trained_group and trained_group != self.config.data.group_column:
            raise ValueError(
                f"El modelo fue entrenado agrupando por '{trained_group}' y ahora se usa "
                f"'{self.config.data.group_column}'."
            )

    def predict(self, input_path: str | Path | None = None) -> pd.DataFrame:
        source = self.config.data.source
        if input_path is not None:
            path = Path(input_path).resolve()
            if not path.exists():
                raise FileNotFoundError(f"No existe el archivo de entrada: {path}")
            source.path = path
            if path.suffix.lower() == ".csv":
                source.type = "csv"
            elif path.suffix.lower() == ".parquet":
                source.type = "parquet"
            else:
                source.type = "excel"

        raw = load_dataset(source)
        validate_raw_dataset(raw, self.config)
        cycle_df = prepare_cycle_data(raw, self.config)
        turno_df = aggregate_to_turno(cycle_df, self.config)

        feature_columns = [str(column) for column in self.metadata["feature_columns"]]
        missing = [column for column in feature_columns if column not in turno_df.columns]
        if missing:
            raise ValueError(
                "Faltan features que el modelo espera: " + ", ".join(missing)
            )
        X = turno_df[feature_columns]
        X_transformed = self.preprocessor.transform(X)
        predictions = self.model.predict(X_transformed)
        indices = np.arange(len(turno_df))
        frame = build_prediction_frame(
            turno_df=turno_df,
            indices=indices,
            predictions=predictions,
            config=self.config,
            model_name=self.model_name,
            split="predict",
        )
        self.logger.info(
            "Predicción generada para %s turnos con el modelo %s.",
            len(frame),
            self.model_name,
        )
        return frame


def save_predictions(
    frame: pd.DataFrame,
    output_path: str | Path,
    model_name: str,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.suffix.lower() == ".csv":
        frame.to_csv(output, index=False)
        return output

    summary_columns = [
        column
        for column in [
            "modelo",
            "Fecha",
            "Fundo",
            "Modulo",
            "Turno",
            "N_ciclos_pred",
            "Riego_total_pred_m3",
        ]
        if column in frame.columns
    ]
    for slot in range(1, 20):
        for suffix in ("inicio", "fin"):
            column = f"Hora_{suffix}_{slot}_pred_min_hhmm"
            if column in frame.columns:
                summary_columns.append(column)
    summary = frame[summary_columns].copy()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        frame.to_excel(writer, sheet_name="Predicciones", index=False)
        summary.to_excel(writer, sheet_name="Resumen", index=False)
        for sheet_name, sheet_frame in (
            ("Predicciones", frame),
            ("Resumen", summary),
        ):
            worksheet = writer.sheets[sheet_name]
            worksheet.freeze_panes = "A2"
            worksheet.autofilter(
                0, 0, len(sheet_frame), max(0, len(sheet_frame.columns) - 1)
            )
    return output
