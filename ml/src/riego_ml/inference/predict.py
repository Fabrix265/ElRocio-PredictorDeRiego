from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from riego_ml.config.schema import RunConfig
from riego_ml.preprocessing.cleaning import minutes_to_hhmm
from riego_ml.utils.logging import configure_logging


class Predictor:
    def __init__(self, config: RunConfig, model_name: str = "mejor_modelo"):
        self.config = config
        self.model_name = model_name
        self.logger = configure_logging()
        self.bundle_path = self._resolve_bundle_path(model_name)
        self.bundle = joblib.load(self.bundle_path)
        self.turno_model = self.bundle["turno"]["model"]
        self.turno_preprocessor = self.bundle["turno"]["preprocessor"]
        self.turno_features = list(self.bundle["turno"]["feature_columns"])
        self.ciclo_model = self.bundle["ciclo"]["model"]
        self.ciclo_preprocessor = self.bundle["ciclo"]["preprocessor"]
        self.ciclo_features = list(self.bundle["ciclo"]["feature_columns"])
        self.target_columns = list(self.bundle["ciclo"]["target_columns"])
        self.max_cycles = int(self.bundle["ciclo"]["max_cycles"])
        self.id_columns = list(self.bundle["data"]["id_columns"])
        self._validate_bundle()

    def _resolve_bundle_path(self, model_name: str) -> Path:
        candidate = Path(model_name)
        if candidate.suffix.lower() in {".joblib", ".pkl", ".pickle"}:
            if not candidate.exists():
                raise FileNotFoundError(f"No existe el bundle: {candidate}")
            return candidate
        if candidate.exists():
            return candidate
        if model_name in {"mejor", "mejor_modelo"}:
            path = Path(self.config.models_dir) / "v2" / "mejor_modelo_riego.joblib"
        else:
            path = Path(self.config.models_dir) / "v2" / model_name / "modelo_riego.joblib"
        if not path.exists():
            raise FileNotFoundError(
                f"No existe el modelo '{model_name}' en {path}. Entrena primero."
            )
        return path

    def _validate_bundle(self) -> None:
        if int(self.bundle.get("bundle_version", 0)) != 2:
            raise ValueError(
                "El bundle no corresponde al pipeline V2. Vuelve a entrenar los modelos."
            )

    def predict(
        self,
        input_path: str | Path | None = None,
        frame: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        if frame is None:
            if input_path is None:
                input_path = self.config.data.turno_file
            if input_path is None:
                raise ValueError(
                    "Debes indicar input_path o un DataFrame con el formato de turno_dia."
                )
            path = Path(input_path)
            if not path.exists():
                raise FileNotFoundError(f"No existe el archivo de entrada: {path}")
            frame = pd.read_csv(path)

        missing = [column for column in self.turno_features if column not in frame.columns]
        if missing:
            raise ValueError(
                "Faltan features de turno/día que el modelo espera: " + ", ".join(missing)
            )

        work = frame.reset_index(drop=True)
        X_turno = self.turno_preprocessor.transform(work[self.turno_features])
        turno_predictions = self.turno_model.predict(X_turno)
        n_ciclos = np.rint(np.asarray(turno_predictions["n_ciclos"], dtype=float))
        n_ciclos = np.clip(n_ciclos, 1, self.max_cycles).astype(int)

        cycle_frame = self._build_cycle_frame(work, n_ciclos)
        X_ciclo = self.ciclo_preprocessor.transform(cycle_frame[self.ciclo_features])
        cycle_predictions = self.ciclo_model.predict(X_ciclo)

        for i, slot in enumerate(cycle_frame["ciclo_slot"].astype(int)):
            for target in self.target_columns:
                cycle_frame.at[i, target] = float(
                    cycle_predictions[f"{target}_ciclo_{slot}"][i]
                )

        result = cycle_frame[
            [*[c for c in self.id_columns if c in cycle_frame.columns], "n_ciclos", "ciclo_slot", *self.target_columns]
        ].rename(columns={"ciclo_slot": "ciclo"})
        result["fin_min"] = result["inicio_min"] + result["duracion_min"]
        result["hora_inicio"] = result["inicio_min"].map(minutes_to_hhmm)
        result["hora_fin"] = result["fin_min"].map(minutes_to_hhmm)
        result["modelo"] = self.bundle["model_name"]
        result = result.reset_index(drop=True)
        self.logger.info(
            "Predicción generada: %s turnos y %s ciclos con %s.",
            len(work),
            len(result),
            self.bundle["model_name"],
        )
        return result

    def _build_cycle_frame(
        self, turno_frame: pd.DataFrame, n_ciclos: np.ndarray
    ) -> pd.DataFrame:
        rows: list[dict[str, Any]] = []
        for i, count in enumerate(n_ciclos):
            base = turno_frame.iloc[i]
            for slot in range(1, int(count) + 1):
                row: dict[str, Any] = {
                    column: base[column]
                    for column in self.ciclo_features
                    if column in base.index
                }
                row["ciclo_slot"] = slot
                row["n_ciclos"] = int(count)
                for column in self.id_columns:
                    if column in base.index:
                        row[column] = base[column]
                self._fill_previous_cycle_features(row, base)
                rows.append(row)
        return pd.DataFrame(rows)

    def _fill_previous_cycle_features(
        self, row: dict[str, Any], base: pd.Series
    ) -> None:
        previous_cycles = base.get("prev_n_ciclos", np.nan)
        denominator = (
            float(previous_cycles)
            if pd.notna(previous_cycles) and float(previous_cycles) > 0
            else 1.0
        )
        if "prev_m3ha_ciclo" in self.ciclo_features:
            value = row.get("prev_m3ha_ciclo", np.nan)
            if pd.isna(value):
                total = base.get("prev_riego_total_m3ha", np.nan)
                value = float(total) / denominator if pd.notna(total) else np.nan
            row["prev_m3ha_ciclo"] = value
        if "prev_dur_ciclo" in self.ciclo_features:
            value = row.get("prev_dur_ciclo", np.nan)
            if pd.isna(value):
                total = base.get("prev_duracion_total_min", np.nan)
                value = float(total) / denominator if pd.notna(total) else np.nan
            row["prev_dur_ciclo"] = value
        if "prev_inicio_ciclo" in self.ciclo_features:
            value = row.get("prev_inicio_ciclo", np.nan)
            if pd.isna(value):
                value = base.get("prev_inicio_primer_min", np.nan)
            row["prev_inicio_ciclo"] = value
        if "prev_fin_ciclo" in self.ciclo_features:
            value = row.get("prev_fin_ciclo", np.nan)
            if pd.isna(value):
                value = base.get("prev_fin_ultimo_min", np.nan)
            row["prev_fin_ciclo"] = value


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

    summary = (
        frame.groupby([c for c in ["Fecha", "Fundo", "Modulo", "Turno"] if c in frame.columns], dropna=False)
        .agg(
            n_ciclos=("ciclo", "count"),
            riego_total_m3ha=("riego_m3ha", "sum"),
            duracion_total_min=("duracion_min", "sum"),
            inicio_primer_min=("inicio_min", "min"),
            fin_ultimo_min=("fin_min", "max"),
        )
        .reset_index()
    )
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
