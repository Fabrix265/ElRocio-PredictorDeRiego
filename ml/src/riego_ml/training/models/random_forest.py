from __future__ import annotations

from typing import Any

import numpy as np
from sklearn.base import clone
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

from riego_ml.features.targets import TargetSpec
from riego_ml.training.base import BaseMultiTargetModel


class RandomForestModel(BaseMultiTargetModel):
    name = "random_forest"
    supports_early_stopping = True
    scale_numeric = False

    def _make_classifier(self) -> RandomForestClassifier:
        params = self._filter_params(RandomForestClassifier, self.params)
        return RandomForestClassifier(
            random_state=self.random_state, n_jobs=-1, **params
        )

    def _make_regressor(self) -> RandomForestRegressor:
        params = self._filter_params(RandomForestRegressor, self.params)
        return RandomForestRegressor(
            random_state=self.random_state, n_jobs=-1, **params
        )

    def _fit_one(
        self,
        model: Any,
        spec: TargetSpec,
        X_train: np.ndarray,
        y_train: np.ndarray,
        X_val: np.ndarray,
        y_val: np.ndarray,
    ) -> tuple[Any, Any]:
        if not self.early_stopping.get("enabled", False):
            model.fit(X_train, y_train)
            return model, {}

        step = max(1, int(self.early_stopping.get("step", 50)))
        patience = max(1, int(self.early_stopping.get("patience", 10)))
        max_iter = max(
            step,
            int(
                self.early_stopping.get(
                    "max_iter", self.params.get("n_estimators", 300)
                )
            ),
        )

        model.set_params(warm_start=True, n_estimators=step)
        best_score = np.inf
        best_estimators = step
        no_improvement = 0
        history: dict[str, list[Any]] = {
            "iteration": [],
            "metric": [],
            "value": [],
        }

        for n_estimators in range(step, max_iter + 1, step):
            model.set_params(n_estimators=n_estimators)
            model.fit(X_train, y_train)
            score, value, metric = self._validation_score(model, spec, X_val, y_val)
            history["iteration"].append(n_estimators)
            history["metric"].append(metric)
            history["value"].append(value)
            if score < best_score - 1e-12:
                best_score = score
                best_estimators = n_estimators
                no_improvement = 0
            else:
                no_improvement += 1
                if no_improvement >= patience:
                    break

        final_model = clone(model).set_params(
            warm_start=False, n_estimators=best_estimators
        )
        final_model.fit(X_train, y_train)
        return final_model, history
