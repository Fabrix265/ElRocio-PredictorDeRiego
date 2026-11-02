from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBClassifier, XGBRegressor

from riego_ml.features.targets import TargetSpec
from riego_ml.training.base import BaseMultiTargetModel


class XGBoostModel(BaseMultiTargetModel):
    name = "xgboost"
    supports_early_stopping = True
    scale_numeric = False

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.label_encoders_: dict[str, LabelEncoder] = {}

    def _make_classifier(self) -> XGBClassifier:
        params = self._filter_params(XGBClassifier, self.params)
        params.setdefault("objective", "multi:softprob")
        params.setdefault("eval_metric", "mlogloss")
        return XGBClassifier(random_state=self.random_state, n_jobs=-1, **params)

    def _make_regressor(self) -> XGBRegressor:
        params = self._filter_params(XGBRegressor, self.params)
        params.setdefault("objective", "reg:squarederror")
        params.setdefault("eval_metric", "rmse")
        return XGBRegressor(random_state=self.random_state, n_jobs=-1, **params)

    def _fit_one(
        self,
        model: Any,
        spec: TargetSpec,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> tuple[Any, Any]:
        if spec.kind == "classification":
            encoder = LabelEncoder()
            y_train_fit = encoder.fit_transform(y_train)
            self.label_encoders_[spec.name] = encoder
            model.set_params(num_class=len(encoder.classes_))
            if len(y_val):
                y_val_fit = encoder.transform(y_val)
            else:
                y_val_fit = y_val
        else:
            y_train_fit = y_train
            y_val_fit = y_val

        if not self.early_stopping.get("enabled", False) or len(y_val_fit) == 0:
            model.fit(X_train, y_train_fit)
            return model, {}

        rounds = max(1, int(self.early_stopping.get("rounds", 50)))
        model.set_params(early_stopping_rounds=rounds)
        model.fit(
            X_train,
            y_train_fit,
            eval_set=[(X_val, y_val_fit)],
            verbose=False,
        )
        history = model.evals_result() if hasattr(model, "evals_result") else {}
        return model, history

    def predict(self, X: np.ndarray) -> dict[str, np.ndarray]:
        output: dict[str, np.ndarray] = {}
        for name, model in self.models_.items():
            prediction = model.predict(X)
            encoder = self.label_encoders_.get(name)
            if encoder is not None:
                prediction = encoder.inverse_transform(np.asarray(prediction).astype(int))
            output[name] = prediction
        return output
