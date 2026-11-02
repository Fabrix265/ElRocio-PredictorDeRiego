from __future__ import annotations

from riego_ml.config.schema import ModelConfig
from riego_ml.training.base import BaseMultiTargetModel
from riego_ml.training.models import (
    MLPModel,
    RandomForestModel,
    SVRModel,
    XGBoostModel,
)

MODEL_REGISTRY: dict[str, type[BaseMultiTargetModel]] = {
    "random_forest": RandomForestModel,
    "xgboost": XGBoostModel,
    "svr": SVRModel,
    "mlp": MLPModel,
}

ALIASES = {
    "rf": "random_forest",
    "randomforest": "random_forest",
    "xgb": "xgboost",
    "xgboost_model": "xgboost",
    "svm": "svr",
    "svc": "svr",
    "neural_network": "mlp",
    "mlp_regressor": "mlp",
}


def resolve_model_name(name: str) -> str:
    key = name.strip().lower()
    return ALIASES.get(key, key)


def build_model(
    name: str,
    config: ModelConfig,
    random_state: int = 42,
) -> BaseMultiTargetModel:
    key = resolve_model_name(name)
    if key not in MODEL_REGISTRY:
        available = ", ".join(sorted(MODEL_REGISTRY))
        raise ValueError(f"Modelo no soportado: {name}. Disponibles: {available}")
    model_class = MODEL_REGISTRY[key]
    return model_class(
        params=config.params,
        early_stopping=config.early_stopping,
        random_state=random_state,
    )
