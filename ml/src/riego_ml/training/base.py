from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score
from sklearn.preprocessing import StandardScaler

from riego_ml.features.targets import TargetSpec


class BaseMultiTargetModel(ABC):
    name = "base"
    supports_early_stopping = False
    scale_numeric = False
    scale_target = False

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        early_stopping: dict[str, Any] | None = None,
        random_state: int = 42,
    ):
        self.params = dict(params or {})
        self.early_stopping = dict(early_stopping or {})
        self.random_state = int(random_state)
        self.models_: dict[str, Any] = {}
        self.histories_: dict[str, Any] = {}
        self.feature_names_: list[str] = []
        self.target_specs_: list[TargetSpec] = []
        self.target_scalers_: dict[str, StandardScaler] = {}

    @abstractmethod
    def _make_classifier(self) -> Any:
        raise NotImplementedError

    @abstractmethod
    def _make_regressor(self) -> Any:
        raise NotImplementedError

    def _filter_params(self, estimator_class: Any, params: dict[str, Any]) -> dict[str, Any]:
        try:
            parameters = inspect.signature(estimator_class.__init__).parameters
        except (TypeError, ValueError):
            return dict(params)
        if any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return dict(params)
        allowed = {
            name
            for name, parameter in parameters.items()
            if name != "self" and parameter.kind is not inspect.Parameter.VAR_KEYWORD
        }
        return {key: value for key, value in params.items() if key in allowed}

    def _fit_one(
        self,
        model: Any,
        spec: TargetSpec,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> tuple[Any, Any]:
        model.fit(X_train, y_train)
        return model, {}

    def _scale_y(
        self, spec: TargetSpec, y_train: np.ndarray, y_val: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        if spec.kind != "regression" or not self.scale_target:
            return y_train, y_val
        scaler = StandardScaler()
        train = np.asarray(y_train, dtype=float).reshape(-1, 1)
        scaler.fit(train)
        self.target_scalers_[spec.name] = scaler
        scaled_train = scaler.transform(train).ravel()
        if len(y_val) == 0:
            return scaled_train, np.asarray(y_val, dtype=float)
        validation = np.asarray(y_val, dtype=float).reshape(-1, 1)
        return scaled_train, scaler.transform(validation).ravel()

    def _inverse_y(self, spec: TargetSpec, prediction: Any) -> np.ndarray:
        values = np.asarray(prediction)
        scaler = self.target_scalers_.get(spec.name)
        if scaler is None:
            return values
        return scaler.inverse_transform(values.reshape(-1, 1)).ravel()

    def _validation_score(
        self, model: Any, spec: TargetSpec, X_val: np.ndarray, y_val: np.ndarray
    ) -> tuple[float, float, str]:
        if len(y_val) == 0:
            return np.inf, np.nan, "empty"
        prediction = model.predict(X_val)
        if spec.kind == "classification":
            value = float(accuracy_score(y_val, prediction))
            return -value, value, "accuracy"
        prediction = self._inverse_y(spec, prediction)
        error = np.asarray(prediction, dtype=float) - np.asarray(y_val, dtype=float)
        value = float(np.sqrt(np.mean(error**2)))
        return value, value, "rmse"

    def fit(
        self,
        X_train: np.ndarray,
        y_train: dict[str, pd.Series],
        X_val: np.ndarray,
        y_val: dict[str, pd.Series],
        target_specs: list[TargetSpec],
        feature_names: list[str],
    ) -> "BaseMultiTargetModel":
        self.feature_names_ = list(feature_names)
        self.target_specs_ = list(target_specs)

        for spec in target_specs:
            y_tr_full = y_train[spec.name]
            mask_train = ~pd.isna(y_tr_full).to_numpy()
            if not mask_train.any():
                raise ValueError(f"No hay filas de entrenamiento para el target {spec.name}.")
            X_tr = X_train[mask_train]
            y_tr = np.asarray(y_tr_full)[mask_train]

            y_val_full = y_val[spec.name]
            mask_val = ~pd.isna(y_val_full).to_numpy()
            X_va = X_val[mask_val]
            y_va = np.asarray(y_val_full)[mask_val]

            if spec.kind == "classification":
                model = self._make_classifier()
                y_tr = y_tr.astype(int)
                y_va = y_va.astype(int)
                if len(np.unique(y_tr)) < 2:
                    raise ValueError(
                        f"El target de clasificación {spec.name} tiene una sola clase en train."
                    )
            else:
                model = self._make_regressor()
                y_tr = y_tr.astype(float)
                y_va = y_va.astype(float)
                y_tr, y_va = self._scale_y(spec, y_tr, y_va)

            model, history = self._fit_one(model, spec, X_tr, y_tr, X_va, y_va)
            self.models_[spec.name] = model
            self.histories_[spec.name] = history

        return self

    def predict(self, X: np.ndarray) -> dict[str, np.ndarray]:
        output: dict[str, np.ndarray] = {}
        for spec in self.target_specs_:
            model = self.models_.get(spec.name)
            if model is None:
                continue
            prediction = model.predict(X)
            if spec.kind == "regression":
                prediction = self._inverse_y(spec, prediction)
            output[spec.name] = prediction
        return output

    def predict_proba(self, X: np.ndarray) -> dict[str, np.ndarray]:
        output: dict[str, np.ndarray] = {}
        for name, model in self.models_.items():
            if hasattr(model, "predict_proba"):
                output[name] = model.predict_proba(X)
        return output

    def feature_importance(self, target: str) -> pd.Series | None:
        model = self.models_.get(target)
        if model is None or not hasattr(model, "feature_importances_"):
            return None
        importance = np.asarray(model.feature_importances_, dtype=float)
        if importance.shape[0] != len(self.feature_names_):
            return None
        return pd.Series(importance, index=self.feature_names_).sort_values(
            ascending=False
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self, target, compress=3)
        return target

    @classmethod
    def load(cls, path: str | Path) -> "BaseMultiTargetModel":
        return joblib.load(path)

    def get_history(self, target: str) -> Any:
        return self.histories_.get(target, {})
