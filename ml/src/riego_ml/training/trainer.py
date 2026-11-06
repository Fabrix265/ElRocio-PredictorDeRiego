from __future__ import annotations

import json
import shutil
import warnings
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning

from riego_ml.config.schema import ModelConfig, RunConfig
from riego_ml.data.v2 import (
    V2Dataset,
    ciclo_feature_columns,
    load_v2_dataset,
    turno_feature_columns,
)
from riego_ml.evaluation.metrics import classification_metrics, regression_metrics
from riego_ml.features.build import build_preprocessor
from riego_ml.features.targets import (
    TargetSpec,
    build_v2_cycle_specs,
    build_v2_turno_specs,
)
from riego_ml.preprocessing.split import (
    SplitIndices,
    expanding_window_folds,
    split_from_boundaries,
    temporal_boundaries,
)
from riego_ml.training.registry import build_model
from riego_ml.training.tuning import tune_params
from riego_ml.utils.io import save_json
from riego_ml.utils.logging import configure_logging
from riego_ml.utils.paths import ensure_dir, run_id
from riego_ml.utils.reproducibility import environment_info, file_sha256, set_seeds


class Trainer:
    def __init__(self, config: RunConfig, logger: Any | None = None):
        self.config = config
        self.logger = logger or configure_logging()
        self.reports_dir = ensure_dir(config.reports_dir)
        self.models_dir = ensure_dir(config.models_dir)
        self.v2_dir = ensure_dir(self.models_dir / "v2")
        self.run_id = run_id(config.name)

        self.classification_rows: list[dict[str, Any]] = []
        self.regression_rows: list[dict[str, Any]] = []
        self.model_rows: list[dict[str, Any]] = []
        self.target_rows: list[dict[str, Any]] = []
        self.model_status: list[dict[str, Any]] = []
        self.tuning_rows: list[dict[str, Any]] = []
        self._dataset_hash = ""
        self._best_score = -np.inf
        self._best_model: str | None = None
        self._best_bundle: Path | None = None

    def run(self) -> dict[str, Any]:
        set_seeds(self.config.seed)
        self.logger.info("Iniciando entrenamiento: %s", self.run_id)

        dataset = load_v2_dataset(self.config)
        turno = dataset.turno
        ciclos = dataset.ciclos
        turno_features = turno_feature_columns(dataset, self.config)
        ciclo_features = ciclo_feature_columns(dataset, self.config)
        turno_specs = build_v2_turno_specs(self.config)
        ciclo_specs = build_v2_cycle_specs(self.config)

        boundaries = temporal_boundaries(turno, self.config)
        splits_turno = split_from_boundaries(turno, boundaries, self.config)
        splits_ciclo = split_from_boundaries(ciclos, boundaries, self.config)
        self._dataset_hash = self._hash_inputs()
        self._log_split(turno, splits_turno, "turno")
        self._log_split(ciclos, splits_ciclo, "ciclo")
        self._save_dataset_summary(dataset, turno_features, ciclo_features, turno_specs, ciclo_specs)
        self._save_config_snapshot()

        self.target_rows = [
            {**asdict(spec), "stage": "turno"} for spec in turno_specs
        ] + [{**asdict(spec), "stage": "ciclo"} for spec in ciclo_specs]

        successful = 0
        for model_name, model_config in self.config.models.items():
            if not model_config.enabled:
                self.logger.info("Modelo deshabilitado: %s", model_name)
                self.model_rows.append(
                    {
                        "model": model_name,
                        "enabled": False,
                        "status": "deshabilitado",
                        "params": model_config.params,
                        "error": "",
                    }
                )
                continue
            try:
                self._train_one(
                    model_name=model_name,
                    model_config=model_config,
                    turno=turno,
                    ciclos=ciclos,
                    turno_features=turno_features,
                    ciclo_features=ciclo_features,
                    turno_specs=turno_specs,
                    ciclo_specs=ciclo_specs,
                    splits_turno=splits_turno,
                    splits_ciclo=splits_ciclo,
                )
                successful += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("Error entrenando el modelo %s", model_name)
                self.model_rows.append(
                    {
                        "model": model_name,
                        "enabled": True,
                        "status": "error",
                        "params": model_config.params,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
                self.model_status.append(
                    {
                        "model": model_name,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        if successful == 0:
            raise RuntimeError(
                "Ningún modelo terminó correctamente. Revisa el log y los errores reportados."
            )

        self._save_metrics()
        self._select_best_model()
        self._save_run_metadata(splits_turno, successful)
        if self.config.evaluation.generate_excel:
            self._write_excel_report()

        summary = {
            "run_id": self.run_id,
            "turnos": len(turno),
            "ciclos": len(ciclos),
            "features_turno": len(turno_features),
            "features_ciclo": len(ciclo_features),
            "modelos_ok": successful,
            "mejor_modelo": self._best_model,
            "modelos_dir": str(self.v2_dir),
            "reporte_dir": str(self.reports_dir),
        }
        self.logger.info("Entrenamiento finalizado: %s", summary)
        return summary

    def _train_one(
        self,
        model_name: str,
        model_config: ModelConfig,
        turno: pd.DataFrame,
        ciclos: pd.DataFrame,
        turno_features: list[str],
        ciclo_features: list[str],
        turno_specs: list[TargetSpec],
        ciclo_specs: list[TargetSpec],
        splits_turno: SplitIndices,
        splits_ciclo: SplitIndices,
    ) -> None:
        self.logger.info("Entrenando modelo: %s", model_name)
        params, tuning_info = self._tune(
            model_name, model_config, turno, ciclos, turno_features, ciclo_features, splits_turno, splits_ciclo
        )
        if tuning_info:
            row: dict[str, Any] = {
                "model": model_name,
                "target": tuning_info.get("target"),
            }
            for stage, result in tuning_info.items():
                if stage == "target" or not isinstance(result, dict):
                    continue
                row[f"{stage}_best_score"] = result.get("best_score")
                row[f"{stage}_scoring"] = result.get("scoring")
                row[f"{stage}_params"] = result.get("params")
            self.tuning_rows.append(row)
        stage_config = ModelConfig(
            enabled=True,
            params=params,
            early_stopping=dict(model_config.early_stopping),
        )

        turno_model, turno_pre = self._fit_stage(
            model_name=model_name,
            model_config=stage_config,
            frame=turno,
            features=turno_features,
            specs=turno_specs,
            splits=splits_turno,
            stage="turno",
        )
        turno_predictions = self._predict_splits(
            turno_model, turno_pre, turno, turno_features, splits_turno
        )
        self._evaluate_classification(
            model_name, turno, turno_specs[0], splits_turno, turno_predictions
        )

        ciclo_model, ciclo_pre = self._fit_stage(
            model_name=model_name,
            model_config=stage_config,
            frame=ciclos,
            features=ciclo_features,
            specs=ciclo_specs,
            splits=splits_ciclo,
            stage="ciclo",
        )
        ciclo_predictions = self._predict_splits(
            ciclo_model, ciclo_pre, ciclos, ciclo_features, splits_ciclo
        )
        self._evaluate_regression(
            model_name, ciclos, ciclo_specs, splits_ciclo, ciclo_predictions
        )

        self._save_model_artifacts(
            model_name=model_name,
            stage_config=stage_config,
            turno_model=turno_model,
            turno_pre=turno_pre,
            turno_features=turno_features,
            turno_specs=turno_specs,
            splits_turno=splits_turno,
            ciclo_model=ciclo_model,
            ciclo_pre=ciclo_pre,
            ciclo_features=ciclo_features,
            ciclo_specs=ciclo_specs,
            splits_ciclo=splits_ciclo,
            tuning_info=tuning_info,
        )

        self.model_rows.append(
            {
                "model": model_name,
                "enabled": True,
                "status": "ok",
                "params": params,
                "error": "",
            }
        )
        self.model_status.append({"model": model_name, "status": "ok", "error": ""})
        self.logger.info("Modelo %s finalizado.", model_name)

    def _tune(
        self,
        model_name: str,
        model_config: ModelConfig,
        turno: pd.DataFrame,
        ciclos: pd.DataFrame,
        turno_features: list[str],
        ciclo_features: list[str],
        splits_turno: SplitIndices,
        splits_ciclo: SplitIndices,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        params = dict(model_config.params)
        if not self.config.tuning.enabled:
            return params, {}
        tuning = self.config.tuning
        info: dict[str, Any] = {"target": tuning.target}
        choice = tuning.target
        if choice in {"n_ciclos", "both"}:
            train = turno.iloc[splits_turno.train].reset_index(drop=True)
            folds = expanding_window_folds(train, self.config, tuning.cv_splits)
            result = tune_params(
                model_name=model_name,
                model_config=model_config,
                X=train[turno_features],
                y=train["n_ciclos_clase"],
                spec=build_v2_turno_specs(self.config)[0],
                folds=folds,
                categorical_features=[],
                numeric_features=turno_features,
                tuning=tuning,
                random_state=self.config.seed,
            )
            params.update(result["params"])
            info["n_ciclos"] = result
        if choice in {"ciclo", "riego_m3ha", "both"}:
            target_column = self.config.data.target_cycle_columns[0]
            train = ciclos.iloc[splits_ciclo.train].reset_index(drop=True)
            folds = expanding_window_folds(train, self.config, tuning.cv_splits)
            spec = TargetSpec(
                name=target_column,
                column=target_column,
                kind="regression",
                description=f"Tuning sobre {target_column}.",
            )
            result = tune_params(
                model_name=model_name,
                model_config=model_config,
                X=train[ciclo_features],
                y=train[target_column],
                spec=spec,
                folds=folds,
                categorical_features=[],
                numeric_features=ciclo_features,
                tuning=tuning,
                random_state=self.config.seed,
            )
            params.update(result["params"])
            info["ciclo"] = result
        return params, info

    def _fit_stage(
        self,
        model_name: str,
        model_config: ModelConfig,
        frame: pd.DataFrame,
        features: list[str],
        specs: list[TargetSpec],
        splits: SplitIndices,
        stage: str,
    ) -> tuple[Any, Any]:
        model = build_model(model_name, model_config, random_state=self.config.seed)
        preprocessor = build_preprocessor(
            [], features, scale_numeric=model.scale_numeric
        )
        preprocessor.fit(frame.iloc[splits.train][features])
        feature_names = [str(name) for name in preprocessor.get_feature_names_out()]

        X_train = preprocessor.transform(frame.iloc[splits.train][features])
        X_validation = preprocessor.transform(frame.iloc[splits.validation][features]) if len(splits.validation) else X_train
        validation_indices = splits.validation if len(splits.validation) else splits.train
        y_train = {spec.name: frame.iloc[splits.train][spec.column] for spec in specs}
        y_validation = {
            spec.name: frame.iloc[validation_indices][spec.column] for spec in specs
        }

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=ConvergenceWarning)
            warnings.simplefilter("ignore", category=UserWarning)
            model.fit(
                X_train,
                y_train,
                X_validation,
                y_validation,
                specs,
                feature_names,
            )
        self.logger.info("Etapa %s entrenada para %s.", stage, model_name)
        return model, preprocessor

    def _predict_splits(
        self,
        model: Any,
        preprocessor: Any,
        frame: pd.DataFrame,
        features: list[str],
        splits: SplitIndices,
    ) -> dict[str, dict[str, np.ndarray]]:
        output: dict[str, dict[str, np.ndarray]] = {}
        for split_name, indices in (
            ("train", splits.train),
            ("validation", splits.validation),
            ("test", splits.test),
        ):
            if len(indices) == 0:
                continue
            X = preprocessor.transform(frame.iloc[indices][features])
            output[split_name] = model.predict(X)
        return output

    def _evaluate_classification(
        self,
        model_name: str,
        frame: pd.DataFrame,
        spec: TargetSpec,
        splits: SplitIndices,
        predictions: dict[str, dict[str, np.ndarray]],
    ) -> None:
        for split_name, indices in (
            ("train", splits.train),
            ("validation", splits.validation),
            ("test", splits.test),
        ):
            split_predictions = predictions.get(split_name)
            if split_predictions is None:
                continue
            y_true = frame.iloc[indices][spec.column].to_numpy()
            y_pred = split_predictions.get(spec.name)
            if y_pred is None:
                continue
            mask = self._eval_mask(frame, indices)
            y_true = y_true[mask]
            y_pred = y_pred[mask]
            metrics = classification_metrics(y_true, y_pred, labels=spec.classes or [])
            self.classification_rows.append(
                {
                    "model": model_name,
                    "stage": "turno",
                    "target": spec.name,
                    "split": split_name,
                    "n": metrics["n"],
                    "accuracy": metrics["accuracy"],
                    "balanced_accuracy": metrics["balanced_accuracy"],
                    "f1_macro": metrics["f1_macro"],
                    "cohen_kappa": metrics["cohen_kappa"],
                    "confusion_matrix": metrics["confusion_matrix"],
                    "labels": metrics["labels"],
                }
            )

    def _evaluate_regression(
        self,
        model_name: str,
        frame: pd.DataFrame,
        specs: list[TargetSpec],
        splits: SplitIndices,
        predictions: dict[str, dict[str, np.ndarray]],
    ) -> None:
        for split_name, indices in (
            ("train", splits.train),
            ("validation", splits.validation),
            ("test", splits.test),
        ):
            split_predictions = predictions.get(split_name)
            if split_predictions is None:
                continue
            mask = self._eval_mask(frame, indices)
            for spec in specs:
                y_true = frame.iloc[indices][spec.column].to_numpy(dtype=float)
                y_pred = np.asarray(split_predictions.get(spec.name, np.full(len(y_true), np.nan)), dtype=float)
                valid = mask & np.isfinite(y_true) & np.isfinite(y_pred)
                if not valid.any():
                    continue
                metrics = regression_metrics(y_true[valid], y_pred[valid])
                self.regression_rows.append(
                    {
                        "model": model_name,
                        "stage": "ciclo",
                        "target": spec.metadata.get("target", spec.name),
                        "slot": spec.slot,
                        "split": split_name,
                        **metrics,
                    }
                )

    def _eval_mask(self, frame: pd.DataFrame, indices: np.ndarray) -> np.ndarray:
        mask = np.ones(len(indices), dtype=bool)
        column = self.config.data.incomplete_column
        if (
            self.config.data.exclude_incomplete_from_eval
            and column in frame.columns
        ):
            mask &= (
                pd.to_numeric(frame.iloc[indices][column], errors="coerce")
                .fillna(0)
                .to_numpy()
                == 0
            )
        return mask

    def _save_model_artifacts(
        self,
        model_name: str,
        stage_config: ModelConfig,
        turno_model: Any,
        turno_pre: Any,
        turno_features: list[str],
        turno_specs: list[TargetSpec],
        splits_turno: SplitIndices,
        ciclo_model: Any,
        ciclo_pre: Any,
        ciclo_features: list[str],
        ciclo_specs: list[TargetSpec],
        splits_ciclo: SplitIndices,
        tuning_info: dict[str, Any],
    ) -> None:
        model_dir = ensure_dir(self.v2_dir / model_name)
        turno_dir = ensure_dir(model_dir / "turno")
        ciclo_dir = ensure_dir(model_dir / "ciclo")
        turno_model.save(turno_dir / "model.joblib")
        ciclo_model.save(ciclo_dir / "model.joblib")
        joblib.dump(turno_pre, turno_dir / "preprocessor.joblib", compress=3)
        joblib.dump(ciclo_pre, ciclo_dir / "preprocessor.joblib", compress=3)

        bundle = {
            "bundle_version": 2,
            "model_name": model_name,
            "trained_at": datetime.now().isoformat(timespec="seconds"),
            "seed": self.config.seed,
            "run_id": self.run_id,
            "dataset_hash": self._dataset_hash,
            "turno": {
                "model": turno_model,
                "preprocessor": turno_pre,
                "feature_columns": turno_features,
                "target_specs": [asdict(spec) for spec in turno_specs],
                "classes": list(self.config.targets.n_ciclos_classes),
                "tail_class": self.config.data.tail_class,
            },
            "ciclo": {
                "model": ciclo_model,
                "preprocessor": ciclo_pre,
                "feature_columns": ciclo_features,
                "target_specs": [asdict(spec) for spec in ciclo_specs],
                "target_columns": list(self.config.data.target_cycle_columns),
                "max_cycles": self.config.data.max_cycles,
            },
            "data": {
                "date_column": self.config.data.date_column,
                "group_column": self.config.data.group_column,
                "id_columns": self.config.data.id_columns,
                "cycle_column": self.config.data.cycle_column,
                "turno_file": str(self.config.data.turno_file),
                "ciclos_file": str(self.config.data.ciclos_file),
                "columns_file": str(self.config.data.columns_file),
            },
            "split": {
                "strategy": splits_turno.strategy,
                "n_train": int(len(splits_turno.train)),
                "n_validation": int(len(splits_turno.validation)),
                "n_test": int(len(splits_turno.test)),
            },
            "tuning": tuning_info,
            "environment": environment_info(),
        }
        bundle_path = joblib.dump(
            bundle, model_dir / "modelo_riego.joblib", compress=3
        )[0]
        metadata = {
            "model_name": model_name,
            "run_id": self.run_id,
            "trained_at": bundle["trained_at"],
            "seed": self.config.seed,
            "dataset_hash": self._dataset_hash,
            "feature_columns_turno": turno_features,
            "feature_columns_ciclo": ciclo_features,
            "target_specs_turno": [asdict(spec) for spec in turno_specs],
            "target_specs_ciclo": [asdict(spec) for spec in ciclo_specs],
            "params": stage_config.params,
            "early_stopping": stage_config.early_stopping,
            "data": bundle["data"],
            "split_turno": {
                "n_train": int(len(splits_turno.train)),
                "n_validation": int(len(splits_turno.validation)),
                "n_test": int(len(splits_turno.test)),
            },
            "split_ciclo": {
                "n_train": int(len(splits_ciclo.train)),
                "n_validation": int(len(splits_ciclo.validation)),
                "n_test": int(len(splits_ciclo.test)),
            },
            "tuning": tuning_info,
            "bundle_path": str(bundle_path),
            "environment": environment_info(),
        }
        save_json(model_dir / "metadata.json", metadata)
        metrics = [
            row
            for row in [*self.classification_rows, *self.regression_rows]
            if row.get("model") == model_name
        ]
        save_json(model_dir / "metrics.json", {"metrics": metrics})
        self.logger.info("Modelo guardado en: %s", bundle_path)

    def _select_best_model(self) -> None:
        classification = {
            row["model"]: float(row["f1_macro"])
            for row in self.classification_rows
            if row["split"] == "test" and np.isfinite(row.get("f1_macro", np.nan))
        }
        regression: dict[str, list[float]] = {}
        for row in self.regression_rows:
            if row["split"] == "test" and np.isfinite(row.get("r2", np.nan)):
                regression.setdefault(row["model"], []).append(float(row["r2"]))
        regression_mean = {
            model: float(np.mean(values)) for model, values in regression.items() if values
        }
        candidates = sorted(set(classification) & set(regression_mean))
        if not candidates:
            return

        classification_rank = pd.Series(classification).rank(ascending=False, method="min")
        regression_rank = pd.Series(regression_mean).rank(ascending=False, method="min")
        ranking = [
            {
                "model": model,
                "classification_rank": float(classification_rank[model]),
                "regression_rank": float(regression_rank[model]),
                "combined_rank": float(
                    classification_rank[model] + regression_rank[model]
                ),
                "f1_macro_test": classification[model],
                "r2_mean_test": regression_mean[model],
            }
            for model in candidates
        ]
        ranking.sort(
            key=lambda row: (
                row["combined_rank"],
                -row["r2_mean_test"],
                -row["f1_macro_test"],
            )
        )
        best = ranking[0]
        self._best_model = str(best["model"])
        self._best_bundle = self.v2_dir / self._best_model / "modelo_riego.joblib"
        self._best_score = float(best["combined_rank"])
        target = self.v2_dir / "mejor_modelo_riego.joblib"
        shutil.copy2(self._best_bundle, target)
        save_json(
            self.v2_dir / "mejor_modelo.json",
            {
                "model": self._best_model,
                "selection": "menor suma de ranks (F1 macro y R2 medio en test)",
                "combined_rank": best["combined_rank"],
                "score_f1_macro_test": best["f1_macro_test"],
                "score_r2_mean_test": best["r2_mean_test"],
                "ranking": ranking,
                "bundle": str(target),
            },
        )
        self.logger.info("Mejor modelo (%s) copiado a %s", self._best_model, target)

    def _save_dataset_summary(
        self,
        dataset: V2Dataset,
        turno_features: list[str],
        ciclo_features: list[str],
        turno_specs: list[TargetSpec],
        ciclo_specs: list[TargetSpec],
    ) -> None:
        save_json(
            self.reports_dir / "dataset_resumen.json",
            {
                "filas_turno": int(len(dataset.turno)),
                "filas_ciclo": int(len(dataset.ciclos)),
                "fechas": int(dataset.turno[self.config.data.date_column].nunique()),
                "n_ciclos": dataset.turno["n_ciclos_clase"]
                .value_counts()
                .sort_index()
                .to_dict(),
                "ciclo_slot": dataset.ciclos["ciclo_slot"]
                .value_counts()
                .sort_index()
                .to_dict(),
                "features_turno": turno_features,
                "features_ciclo": ciclo_features,
                "targets_turno": [asdict(spec) for spec in turno_specs],
                "targets_ciclo": [asdict(spec) for spec in ciclo_specs],
            },
        )

    def _save_metrics(self) -> None:
        save_json(
            self.reports_dir / "metrics.json",
            {
                "classification": self.classification_rows,
                "regression": self.regression_rows,
                "tuning": self.tuning_rows,
            },
        )
        rows: list[dict[str, Any]] = []
        rows.extend(self.classification_rows)
        rows.extend(self.regression_rows)
        frame = pd.DataFrame(rows)
        if not frame.empty:
            frame = frame.drop(columns=["confusion_matrix", "labels"], errors="ignore")
            frame.to_csv(self.reports_dir / "metrics.csv", index=False)

    def _write_excel_report(self) -> None:
        path = self.reports_dir / "metricas_modelos.xlsx"
        classification = pd.DataFrame(self.classification_rows).drop(
            columns=["confusion_matrix", "labels"], errors="ignore"
        )
        regression = pd.DataFrame(self.regression_rows)
        models = pd.DataFrame(self.model_rows)
        tuning = pd.DataFrame(self.tuning_rows)
        for frame in (models, tuning):
            for column in frame.columns:
                if frame[column].map(lambda value: isinstance(value, (dict, list))).any():
                    frame[column] = frame[column].map(
                        lambda value: json.dumps(value, ensure_ascii=False, default=str)
                        if isinstance(value, (dict, list))
                        else value
                    )
        with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
            for name, frame in (
                ("Resumen_Clasificacion", classification),
                ("Resumen_Regresion", regression),
                ("Modelos", models),
                ("Tuning", tuning),
            ):
                if frame.empty:
                    pd.DataFrame({"Mensaje": ["Sin datos"]}).to_excel(
                        writer, sheet_name=name, index=False
                    )
                else:
                    frame.to_excel(writer, sheet_name=name, index=False)
        self.logger.info("Reporte Excel: %s", path)

    def _save_config_snapshot(self) -> None:
        if self.config.config_path and Path(self.config.config_path).exists():
            shutil.copy2(self.config.config_path, self.reports_dir / "config_usada.yaml")
        save_json(self.reports_dir / "config_usada.json", asdict(self.config))

    def _save_run_metadata(self, splits: SplitIndices, successful: int) -> None:
        save_json(
            self.reports_dir / "run_metadata.json",
            {
                "run_id": self.run_id,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "dataset_hash": self._dataset_hash,
                "environment": environment_info(),
                "split": {
                    "strategy": splits.strategy,
                    "n_train": int(len(splits.train)),
                    "n_validation": int(len(splits.validation)),
                    "n_test": int(len(splits.test)),
                    "gap_days": self.config.split.gap_days,
                },
                "modelos_ok": successful,
                "modelos": self.model_status,
                "mejor_modelo": self._best_model,
                "modelos_dir": str(self.v2_dir),
                "reporte_dir": str(self.reports_dir),
            },
        )

    def _hash_inputs(self) -> str:
        parts = []
        for path in (
            self.config.data.turno_file,
            self.config.data.ciclos_file,
            self.config.data.columns_file,
        ):
            if path is not None and Path(path).exists():
                parts.append(f"{Path(path).name}:{file_sha256(path)}")
        return "|".join(parts)

    def _log_split(
        self, frame: pd.DataFrame, splits: SplitIndices, label: str
    ) -> None:
        for name, indices in (
            ("train", splits.train),
            ("validation", splits.validation),
            ("test", splits.test),
        ):
            subset = frame.iloc[indices]
            self.logger.info(
                "Split %-6s %-10s filas=%5s fechas=%4s",
                label,
                name,
                len(indices),
                subset[self.config.data.date_column].nunique() if len(indices) else 0,
            )
