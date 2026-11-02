from __future__ import annotations

import copy
from typing import Any

import numpy as np
from sklearn.neural_network import MLPClassifier, MLPRegressor

from riego_ml.features.targets import TargetSpec
from riego_ml.training.base import BaseMultiTargetModel


class MLPModel(BaseMultiTargetModel):
    name = "mlp"
    supports_early_stopping = True
    scale_numeric = True

    def _make_classifier(self) -> MLPClassifier:
        params = self._filter_params(MLPClassifier, self.params)
        return MLPClassifier(random_state=self.random_state, **params)

    def _make_regressor(self) -> MLPRegressor:
        params = self._filter_params(MLPRegressor, self.params)
        return MLPRegressor(random_state=self.random_state, **params)

    def _fit_one(
        self,
        model: Any,
        spec: TargetSpec,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> tuple[Any, Any]:
        if not self.early_stopping.get("enabled", False) or len(y_val) == 0:
            model.fit(X_train, y_train)
            return model, {}

        patience = max(1, int(self.early_stopping.get("patience", 20)))
        max_epochs = max(
            1,
            int(
                self.early_stopping.get(
                    "max_iter", self.params.get("max_iter", 500)
                )
            ),
        )
        model.set_params(warm_start=True, early_stopping=False, max_iter=1)

        classes = np.unique(y_train) if spec.kind == "classification" else None
        best_score = np.inf
        best_model: Any | None = None
        no_improvement = 0
        history: dict[str, list[Any]] = {
            "iteration": [],
            "metric": [],
            "value": [],
        }

        for epoch in range(1, max_epochs + 1):
            if spec.kind == "classification":
                model.partial_fit(X_train, y_train, classes=classes)
            else:
                model.partial_fit(X_train, y_train)
            score, value, metric = self._validation_score(model, spec, X_val, y_val)
            history["iteration"].append(epoch)
            history["metric"].append(metric)
            history["value"].append(value)
            if score < best_score - 1e-12:
                best_score = score
                best_model = copy.deepcopy(model)
                no_improvement = 0
            else:
                no_improvement += 1
                if no_improvement >= patience:
                    break

        return best_model if best_model is not None else model, history
