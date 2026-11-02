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
from sklearn.inspection import permutation_importance

from riego_ml.config.schema import ModelConfig, RunConfig
from riego_ml.data.loader import load_dataset
from riego_ml.data.validation import validate_raw_dataset, validate_turno_dataset
from riego_ml.evaluation.metrics import classification_metrics, regression_metrics
from riego_ml.evaluation.plots import (
    plot_class_distribution,
    plot_confusion_matrix,
    plot_early_stopping,
    plot_feature_importance,
    plot_metric_by_slot,
    plot_model_comparison,
    plot_pred_vs_obs,
    plot_residual_hist,
    plot_residuals,
    plot_schedule_gantt,
    plot_time_series,
)
from riego_ml.evaluation.report import write_excel_report
from riego_ml.features.aggregate import aggregate_to_turno
from riego_ml.features.build import build_preprocessor
from riego_ml.features.schedule import (
    actual_schedule_frame,
    build_prediction_frame,
    schedule_metrics,
)
from riego_ml.features.targets import (
    TargetSpec,
    build_feature_columns,
    build_target_specs,
    split_xy,
    target_columns,
)
from riego_ml.preprocessing.cleaning import prepare_cycle_data
from riego_ml.preprocessing.split import SplitIndices, split_dataset
from riego_ml.training.registry import build_model, resolve_model_name
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
        self.figures_dir = ensure_dir(self.reports_dir / "figures")
        self.run_id = run_id(config.name)

        self.regression_rows: list[dict[str, Any]] = []
        self.classification_rows: list[dict[str, Any]] = []
        self.schedule_rows: list[dict[str, Any]] = []
        self.prediction_frames: list[pd.DataFrame] = []
        self.errors_frames: list[pd.DataFrame] = []
        self.group_rows: list[dict[str, Any]] = []
        self.model_rows: list[dict[str, Any]] = []
        self.target_rows: list[dict[str, Any]] = []
        self.model_status: list[dict[str, Any]] = []
        self._dataset_hash = ""

    def run(self) -> dict[str, Any]:
        set_seeds(self.config.seed)
        self.logger.info("Iniciando entrenamiento: %s", self.run_id)
        self.logger.info("Config: %s", self.config.config_path)

        raw = load_dataset(self.config.data.source)
        validate_raw_dataset(raw, self.config)
        if self.config.data.source.path is not None:
            self._dataset_hash = file_sha256(self.config.data.source.path)

        cycle_df = prepare_cycle_data(raw, self.config)
        turno_df = aggregate_to_turno(cycle_df, self.config)
        specs = build_target_specs(self.config)
        feature_columns, categorical_features, numeric_features = build_feature_columns(
            turno_df, self.config, specs
        )
        validate_turno_dataset(
            turno_df, feature_columns, target_columns(specs)
        )
        X, y = split_xy(turno_df, feature_columns, specs)
        splits = split_dataset(turno_df, self.config)

        self.logger.info(
            "Filas ciclo=%s | turnos=%s | features=%s | targets=%s",
            len(cycle_df),
            len(turno_df),
            len(feature_columns),
            len(specs),
        )
        self._log_split(turno_df, splits)
        self._save_dataset_summary(cycle_df, turno_df, specs)
        self._save_config_snapshot()

        self.target_rows = [
            {
                "target": spec.name,
                "columna": spec.column,
                "tipo": spec.kind,
                "slot": spec.slot,
                "descripcion": spec.description,
            }
            for spec in specs
        ]

        successful_models = 0
        for model_name, model_config in self.config.models.items():
            if not model_config.enabled:
                self.logger.info("Modelo deshabilitado: %s", model_name)
                self.model_rows.append(
                    {
                        "model": model_name,
                        "enabled": False,
                        "params": model_config.params,
                        "early_stopping": model_config.early_stopping,
                        "status": "deshabilitado",
                        "error": "",
                    }
                )
                continue
            try:
                self._train_one(
                    model_name=model_name,
                    model_config=model_config,
                    X=X,
                    y=y,
                    turno_df=turno_df,
                    specs=specs,
                    categorical_features=categorical_features,
                    numeric_features=numeric_features,
                    feature_columns=feature_columns,
                    splits=splits,
                )
                successful_models += 1
            except Exception as exc:  # noqa: BLE001
                self.logger.exception("Error entrenando el modelo %s", model_name)
                self.model_rows.append(
                    {
                        "model": model_name,
                        "enabled": True,
                        "params": model_config.params,
                        "early_stopping": model_config.early_stopping,
                        "status": "error",
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

        if successful_models == 0:
            raise RuntimeError(
                "Ningún modelo terminó correctamente. Revisa el log y los errores reportados."
            )

        try:
            self._generate_comparison_plots()
        except Exception as exc:  # noqa: BLE001
            self.logger.exception("No se pudieron generar los gráficos comparativos: %s", exc)
        excel_path = self.reports_dir / "metricas_modelos.xlsx"
        if self.config.evaluation.generate_excel:
            write_excel_report(
                path=excel_path,
                regression_rows=self.regression_rows,
                classification_rows=self.classification_rows,
                schedule_rows=self.schedule_rows,
                prediction_frames=self.prediction_frames,
                errors_frames=self.errors_frames,
                group_rows=self.group_rows,
                config_rows=self._config_rows(),
                model_rows=self.model_rows,
                target_rows=self.target_rows,
                max_cycles=self.config.data.max_cycles,
            )
            self.logger.info("Reporte Excel: %s", excel_path)

        self._save_run_metadata(splits, successful_models)
        summary = {
            "run_id": self.run_id,
            "turnos": len(turno_df),
            "features": len(feature_columns),
            "modelos_ok": successful_models,
            "reporte": str(excel_path) if self.config.evaluation.generate_excel else None,
            "modelos_dir": str(self.models_dir),
            "figuras_dir": str(self.figures_dir),
        }
        self.logger.info("Entrenamiento finalizado: %s", summary)
        return summary

    def _train_one(
        self,
        model_name: str,
        model_config: ModelConfig,
        X: pd.DataFrame,
        y: dict[str, pd.Series],
        turno_df: pd.DataFrame,
        specs: list[TargetSpec],
        categorical_features: list[str],
        numeric_features: list[str],
        feature_columns: list[str],
        splits: SplitIndices,
    ) -> None:
        resolved_name = resolve_model_name(model_name)
        self.logger.info("Entrenando modelo: %s", model_name)
        model = build_model(model_name, model_config, random_state=self.config.seed)
        preprocessor = build_preprocessor(
            categorical_features,
            numeric_features,
            scale_numeric=model.scale_numeric,
        )

        X_train_df = X.iloc[splits.train]
        preprocessor.fit(X_train_df)
        feature_names = [str(name) for name in preprocessor.get_feature_names_out()]
        X_train = preprocessor.transform(X_train_df)
        X_test = preprocessor.transform(X.iloc[splits.test])

        if len(splits.validation) > 0:
            X_val = preprocessor.transform(X.iloc[splits.validation])
            validation_indices = splits.validation
        else:
            self.logger.warning(
                "Sin validación para %s; se usa train como validación para early stopping.",
                model_name,
            )
            X_val = X_train
            validation_indices = splits.train

        y_train = {spec.name: y[spec.name].iloc[splits.train] for spec in specs}
        y_val = {spec.name: y[spec.name].iloc[validation_indices] for spec in specs}
        y_test = {spec.name: y[spec.name].iloc[splits.test] for spec in specs}

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=ConvergenceWarning)
            warnings.simplefilter("ignore", category=UserWarning)
            model.fit(
                X_train,
                y_train,
                X_val,
                y_val,
                specs,
                feature_names,
            )

        split_data = {
            "train": (splits.train, X_train),
            "validation": (validation_indices, X_val),
            "test": (splits.test, X_test),
        }
        test_prediction_frame: pd.DataFrame | None = None
        for split_name, (indices, X_split) in split_data.items():
            if len(indices) == 0:
                continue
            predictions = model.predict(X_split)
            prediction_frame = build_prediction_frame(
                turno_df=turno_df,
                indices=indices,
                predictions=predictions,
                config=self.config,
                model_name=model_name,
                split=split_name,
            )
            self.prediction_frames.append(prediction_frame)
            if split_name == "test":
                test_prediction_frame = prediction_frame

            self._evaluate_split(
                model_name=model_name,
                split_name=split_name,
                specs=specs,
                y=y,
                indices=indices,
                predictions=predictions,
                prediction_frame=prediction_frame,
            )

        if test_prediction_frame is None:
            test_prediction_frame = build_prediction_frame(
                turno_df=turno_df,
                indices=splits.test,
                predictions=model.predict(X_test),
                config=self.config,
                model_name=model_name,
                split="test",
            )

        self._save_model_artifacts(
            model_name=model_name,
            model=model,
            preprocessor=preprocessor,
            feature_columns=feature_columns,
            categorical_features=categorical_features,
            numeric_features=numeric_features,
            specs=specs,
            splits=splits,
        )
        try:
            self._make_model_plots(
                model_name=model_name,
                model=model,
                specs=specs,
                y=y,
                test_indices=splits.test,
                test_predictions=model.predict(X_test),
                X_test=X_test,
                feature_names=feature_names,
                turno_df=turno_df,
                test_prediction_frame=test_prediction_frame,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.exception(
                "No se pudieron generar todas las figuras de %s: %s",
                model_name,
                exc,
            )

        self.model_rows.append(
            {
                "model": model_name,
                "enabled": True,
                "params": model_config.params,
                "early_stopping": model_config.early_stopping,
                "status": "ok",
                "error": "",
            }
        )
        self.model_status.append({"model": model_name, "status": "ok", "error": ""})
        self.logger.info("Modelo %s finalizado.", model_name)

    def _evaluate_split(
        self,
        model_name: str,
        split_name: str,
        specs: list[TargetSpec],
        y: dict[str, pd.Series],
        indices: np.ndarray,
        predictions: dict[str, np.ndarray],
        prediction_frame: pd.DataFrame,
    ) -> None:
        for spec in specs:
            y_true = y[spec.name].iloc[indices].to_numpy()
            y_pred = predictions.get(spec.name)
            if y_pred is None:
                continue
            if spec.kind == "classification":
                metrics = classification_metrics(
                    y_true, y_pred, labels=spec.classes or []
                )
                self.classification_rows.append(
                    {
                        "model": model_name,
                        "target": spec.name,
                        "split": split_name,
                        **metrics,
                    }
                )
            else:
                metrics = regression_metrics(y_true, y_pred)
                self.regression_rows.append(
                    {
                        "model": model_name,
                        "target": spec.name,
                        "split": split_name,
                        **metrics,
                    }
                )

        schedule = schedule_metrics(prediction_frame, self.config.data.max_cycles)
        self.schedule_rows.append(
            {
                "model": model_name,
                "split": split_name,
                "n": len(indices),
                **schedule,
            }
        )

        if split_name != "test":
            return

        for spec in specs:
            if spec.kind != "regression":
                continue
            y_true = y[spec.name].iloc[indices].to_numpy(dtype=float)
            y_pred = np.asarray(predictions.get(spec.name, np.full(len(y_true), np.nan)), dtype=float)
            mask = np.isfinite(y_true) & np.isfinite(y_pred)
            if not mask.any():
                continue
            base = prediction_frame.loc[mask, [c for c in self.config.data.id_columns if c in prediction_frame.columns]].copy()
            base["model"] = model_name
            base["target"] = spec.name
            base["real"] = y_true[mask]
            base["predicho"] = y_pred[mask]
            base["error"] = base["predicho"] - base["real"]
            base["error_abs"] = base["error"].abs()
            self.errors_frames.append(
                base.sort_values("error_abs", ascending=False).head(
                    self.config.evaluation.top_errors
                )
            )
            self._append_group_metrics(
                model_name, spec, prediction_frame, y_true, y_pred, mask
            )

    def _append_group_metrics(
        self,
        model_name: str,
        spec: TargetSpec,
        prediction_frame: pd.DataFrame,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        mask: np.ndarray,
    ) -> None:
        group_columns = [
            column
            for column in (self.config.data.date_column, "Modulo", "Fundo")
            if column in prediction_frame.columns
        ]
        if not group_columns:
            return
        temp = prediction_frame.loc[mask, group_columns].copy()
        temp["_real"] = y_true[mask]
        temp["_pred"] = y_pred[mask]
        for keys, group in temp.groupby(group_columns, dropna=False):
            if not isinstance(keys, tuple):
                keys = (keys,)
            metrics = regression_metrics(group["_real"], group["_pred"])
            row = {"model": model_name, "target": spec.name}
            row.update(dict(zip(group_columns, keys)))
            row.update(metrics)
            self.group_rows.append(row)

    def _save_model_artifacts(
        self,
        model_name: str,
        model: Any,
        preprocessor: Any,
        feature_columns: list[str],
        categorical_features: list[str],
        numeric_features: list[str],
        specs: list[TargetSpec],
        splits: SplitIndices,
    ) -> None:
        model_dir = ensure_dir(self.models_dir / model_name)
        model_path = model.save(model_dir / "model.joblib")
        preprocessor_path = model_dir / "preprocessor.joblib"
        joblib.dump(preprocessor, preprocessor_path)

        model_metrics = [
            row
            for row in [*self.regression_rows, *self.classification_rows, *self.schedule_rows]
            if row.get("model") == model_name
        ]
        histories = {
            spec.name: model.get_history(spec.name)
            for spec in specs
            if model.get_history(spec.name)
        }
        metadata = {
            "model_name": model_name,
            "run_id": self.run_id,
            "trained_at": datetime.now().isoformat(timespec="seconds"),
            "seed": self.config.seed,
            "dataset_hash": self._dataset_hash,
            "feature_columns": feature_columns,
            "categorical_features": categorical_features,
            "numeric_features": numeric_features,
            "target_specs": [asdict(spec) for spec in specs],
            "data": {
                "date_column": self.config.data.date_column,
                "group_column": self.config.data.group_column,
                "id_columns": self.config.data.id_columns,
                "environmental_features": self.config.data.environmental_features,
                "max_cycles": self.config.data.max_cycles,
                "nro_ciclo_column": self.config.data.nro_ciclo_column,
                "cycle_volume_column": self.config.data.cycle_volume_column,
                "start_column": self.config.data.start_column,
                "end_column": self.config.data.end_column,
            },
            "targets": asdict(self.config.targets),
            "schedule": asdict(self.config.schedule),
            "split": {
                "strategy": splits.strategy,
                "seed": splits.seed,
                "n_train": int(len(splits.train)),
                "n_validation": int(len(splits.validation)),
                "n_test": int(len(splits.test)),
            },
            "metrics": model_metrics,
            "environment": environment_info(),
        }
        save_json(model_dir / "metadata.json", metadata)
        save_json(model_dir / "metrics.json", {"metrics": model_metrics})
        save_json(model_dir / "histories.json", histories)
        self.logger.info("Artefactos de %s: %s", model_name, model_dir)

    def _make_model_plots(
        self,
        model_name: str,
        model: Any,
        specs: list[TargetSpec],
        y: dict[str, pd.Series],
        test_indices: np.ndarray,
        test_predictions: dict[str, np.ndarray],
        X_test: np.ndarray,
        feature_names: list[str],
        turno_df: pd.DataFrame,
        test_prediction_frame: pd.DataFrame,
    ) -> None:
        if not self.config.evaluation.generate_plots:
            return
        model_figures = ensure_dir(self.figures_dir / model_name)
        test_frame = turno_df.iloc[test_indices].reset_index(drop=True)

        for spec in specs:
            y_true = y[spec.name].iloc[test_indices].to_numpy()
            y_pred = test_predictions.get(spec.name)
            if y_pred is None:
                continue
            if spec.kind == "classification":
                metrics = classification_metrics(
                    y_true, y_pred, labels=spec.classes or []
                )
                plot_confusion_matrix(
                    metrics["confusion_matrix"],
                    metrics["labels"],
                    f"{model_name} · {spec.name}",
                    model_figures / f"{spec.name}_matriz_confusion.png",
                )
                plot_class_distribution(
                    y_true,
                    y_pred,
                    metrics["labels"],
                    f"{model_name} · distribución {spec.name}",
                    model_figures / f"{spec.name}_distribucion.png",
                )
            else:
                plot_pred_vs_obs(
                    y_true,
                    y_pred,
                    f"{model_name} · {spec.name}",
                    model_figures / f"{spec.name}_pred_vs_obs.png",
                )
                plot_residuals(
                    y_true,
                    y_pred,
                    f"{model_name} · residuales {spec.name}",
                    model_figures / f"{spec.name}_residuales.png",
                )
                plot_residual_hist(
                    y_true,
                    y_pred,
                    f"{model_name} · histograma residual {spec.name}",
                    model_figures / f"{spec.name}_residual_hist.png",
                )
                series = test_frame[[c for c in ("Fecha", "Modulo", "Turno") if c in test_frame.columns]].copy()
                series["actual"] = y_true
                series["predicho"] = y_pred
                plot_time_series(
                    series,
                    "actual",
                    "predicho",
                    f"{model_name} · serie {spec.name}",
                    model_figures / f"{spec.name}_serie.png",
                )

            plot_early_stopping(
                model.get_history(spec.name),
                f"{model_name} · early stopping {spec.name}",
                model_figures / f"{spec.name}_early_stopping.png",
            )
            importance = model.feature_importance(spec.name)
            if importance is None:
                importance = self._permutation_importance(
                    model, spec, X_test, y_true, y_pred, feature_names
                )
            plot_feature_importance(
                importance,
                f"{model_name} · importancia {spec.name}",
                model_figures / f"{spec.name}_importancia.png",
            )

        schedule = schedule_metrics(
            test_prediction_frame, self.config.data.max_cycles
        )
        plot_metric_by_slot(
            schedule,
            "mae",
            f"{model_name} · MAE por ciclo",
            model_figures / "mae_por_ciclo.png",
        )
        actual_frame = actual_schedule_frame(
            turno_df, test_indices, self.config
        )
        plot_schedule_gantt(
            actual_frame,
            test_prediction_frame,
            self.config.data.max_cycles,
            f"{model_name} · horarios observados vs predichos",
            model_figures / "horarios_gantt.png",
            max_turnos=self.config.evaluation.max_gantt_turnos,
        )

    def _permutation_importance(
        self,
        model: Any,
        spec: TargetSpec,
        X_test: np.ndarray,
        y_true: np.ndarray,
        y_pred: np.ndarray,
        feature_names: list[str],
    ) -> pd.Series | None:
        if spec.kind == "classification":
            return None
        estimator = model.models_.get(spec.name)
        if estimator is None:
            return None
        true = np.asarray(y_true, dtype=float)
        mask = np.isfinite(true) & np.isfinite(np.asarray(y_pred, dtype=float))
        if mask.sum() < 3:
            return None
        try:
            result = permutation_importance(
                estimator,
                X_test[mask],
                true[mask],
                n_repeats=5,
                random_state=self.config.seed,
                scoring="neg_root_mean_squared_error",
                n_jobs=1,
            )
        except Exception as exc:  # noqa: BLE001
            self.logger.warning(
                "No se pudo calcular importancia por permutación para %s: %s",
                spec.name,
                exc,
            )
            return None
        return pd.Series(
            result.importances_mean, index=feature_names
        ).sort_values(ascending=False)

    def _generate_comparison_plots(self) -> None:
        if not self.config.evaluation.generate_plots:
            return
        comparison_dir = ensure_dir(self.figures_dir / "comparacion")
        regression_df = pd.DataFrame(self.regression_rows)
        if not regression_df.empty:
            test_df = regression_df[regression_df["split"] == "test"]
            for metric in ("rmse", "mae", "r2"):
                plot_model_comparison(
                    test_df,
                    metric,
                    f"Comparación de modelos · {metric.upper()} (test)",
                    comparison_dir / f"comparacion_{metric}.png",
                )
        classification_df = pd.DataFrame(self.classification_rows)
        if not classification_df.empty:
            test_df = classification_df[classification_df["split"] == "test"]
            plot_model_comparison(
                test_df,
                "f1_macro",
                "Comparación de modelos · F1 macro (test)",
                comparison_dir / "comparacion_f1_macro.png",
            )

    def _log_split(self, turno_df: pd.DataFrame, splits: SplitIndices) -> None:
        for name, indices in (
            ("train", splits.train),
            ("validation", splits.validation),
            ("test", splits.test),
        ):
            subset = turno_df.iloc[indices]
            distribution = subset[self.config.targets.n_ciclos_column].value_counts().sort_index().to_dict()
            groups = subset[self.config.data.group_column].nunique()
            self.logger.info(
                "Split %-10s filas=%3s turnos=%2s distribución=%s",
                name,
                len(indices),
                groups,
                distribution,
            )

    def _save_dataset_summary(
        self,
        cycle_df: pd.DataFrame,
        turno_df: pd.DataFrame,
        specs: list[TargetSpec],
    ) -> None:
        summary = {
            "filas_ciclo": int(len(cycle_df)),
            "filas_turno": int(len(turno_df)),
            "fechas": sorted(
                pd.to_datetime(turno_df[self.config.data.date_column])
                .dt.strftime("%Y-%m-%d")
                .unique()
                .tolist()
            ),
            "columnas_ciclo": [str(c) for c in cycle_df.columns],
            "columnas_turno": [str(c) for c in turno_df.columns],
            "targets": [asdict(spec) for spec in specs],
            "n_ciclos": turno_df[self.config.targets.n_ciclos_column]
            .value_counts()
            .sort_index()
            .to_dict(),
        }
        save_json(self.reports_dir / "dataset_resumen.json", summary)
        turno_df.to_csv(self.reports_dir / "dataset_turno.csv", index=False)
        cycle_df.to_csv(self.reports_dir / "dataset_ciclo_limpio.csv", index=False)

    def _save_config_snapshot(self) -> None:
        if self.config.config_path and Path(self.config.config_path).exists():
            shutil.copy2(
                self.config.config_path, self.reports_dir / "config_usada.yaml"
            )
        save_json(
            self.reports_dir / "config_usada.json",
            {
                "name": self.config.name,
                "seed": self.config.seed,
                "data": {
                    "source": {
                        "type": self.config.data.source.type,
                        "path": str(self.config.data.source.path),
                        "sheet": self.config.data.source.sheet,
                        "column_map": self.config.data.source.column_map,
                    },
                    "date_column": self.config.data.date_column,
                    "group_column": self.config.data.group_column,
                    "id_columns": self.config.data.id_columns,
                    "categorical_features": self.config.data.categorical_features,
                    "numeric_features": self.config.data.numeric_features,
                    "environmental_features": self.config.data.environmental_features,
                    "max_cycles": self.config.data.max_cycles,
                },
                "split": asdict(self.config.split),
                "targets": asdict(self.config.targets),
                "models": {
                    name: {
                        "enabled": cfg.enabled,
                        "params": cfg.params,
                        "early_stopping": cfg.early_stopping,
                    }
                    for name, cfg in self.config.models.items()
                },
                "evaluation": asdict(self.config.evaluation),
                "schedule": asdict(self.config.schedule),
            },
        )

    def _save_run_metadata(
        self, splits: SplitIndices, successful_models: int
    ) -> None:
        save_json(
            self.reports_dir / "run_metadata.json",
            {
                "run_id": self.run_id,
                "finished_at": datetime.now().isoformat(timespec="seconds"),
                "dataset_hash": self._dataset_hash,
                "environment": environment_info(),
                "split": {
                    "strategy": splits.strategy,
                    "seed": splits.seed,
                    "n_train": int(len(splits.train)),
                    "n_validation": int(len(splits.validation)),
                    "n_test": int(len(splits.test)),
                },
                "modelos_ok": successful_models,
                "modelos": self.model_status,
                "reporte_excel": str(self.reports_dir / "metricas_modelos.xlsx"),
                "modelos_dir": str(self.models_dir),
                "figuras_dir": str(self.figures_dir),
            },
        )

    def _config_rows(self) -> list[dict[str, Any]]:
        rows = [
            {"clave": "run_id", "valor": self.run_id},
            {"clave": "seed", "valor": self.config.seed},
            {"clave": "dataset_hash", "valor": self._dataset_hash},
            {"clave": "data_source", "valor": str(self.config.data.source.path)},
            {"clave": "max_cycles", "valor": self.config.data.max_cycles},
            {"clave": "split_strategy", "valor": self.config.split.strategy},
            {"clave": "test_size", "valor": self.config.split.test_size},
            {"clave": "validation_size", "valor": self.config.split.validation_size},
            {"clave": "end_mode", "valor": self.config.schedule.end_mode},
        ]
        for name, cfg in self.config.models.items():
            rows.append(
                {
                    "clave": f"modelo_{name}",
                    "valor": json.dumps(
                        {
                            "enabled": cfg.enabled,
                            "params": cfg.params,
                            "early_stopping": cfg.early_stopping,
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                }
            )
        return rows
