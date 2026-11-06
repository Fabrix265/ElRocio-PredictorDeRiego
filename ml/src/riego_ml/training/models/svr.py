from __future__ import annotations

from typing import Any

from sklearn.svm import SVC, SVR

from riego_ml.training.base import BaseMultiTargetModel


class SVRModel(BaseMultiTargetModel):
    name = "svr"
    supports_early_stopping = False
    scale_numeric = True
    scale_target = True

    def _make_classifier(self) -> SVC:
        params = self._filter_params(SVC, self.params)
        return SVC(random_state=self.random_state, **params)

    def _make_regressor(self) -> SVR:
        params = self._filter_params(SVR, self.params)
        return SVR(**params)

    def _fit_one(
        self,
        model: Any,
        spec: Any,
        X_train: Any,
        y_train: Any,
        X_val: Any,
        y_val: Any,
    ) -> tuple[Any, Any]:
        model.fit(X_train, y_train)
        return model, {}
