"""Fábrica de modelos: Random Forest, XGBoost, SVR/SVC y MLP.

Cada estimador es un ``Pipeline`` de scikit-learn que incluye su propio
preprocesamiento (imputación por mediana + indicador de faltante, one-hot de
``Turno`` y escalado para SVR/MLP). Así el preprocesamiento se ajusta solo con
los datos de entrenamiento y viaja dentro del modelo guardado.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.compose import ColumnTransformer, TransformedTargetRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.neural_network import MLPClassifier, MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import LabelEncoder, OneHotEncoder, StandardScaler
from sklearn.svm import SVC, SVR
from xgboost import XGBClassifier, XGBRegressor

FAMILIAS = ("random_forest", "xgboost", "svr", "mlp")
PERSISTENCIA_NOMBRE = "persistencia"
ESCALAN = {"svr", "mlp"}


class XGBEtiquetado(BaseEstimator, ClassifierMixin):
    """XGBClassifier que acepta etiquetas arbitrarias (p. ej. 1..5)."""

    def __init__(self, **params: Any):
        self.params = params

    def get_params(self, deep: bool = True) -> dict[str, Any]:
        return dict(self.params)

    def set_params(self, **params: Any) -> "XGBEtiquetado":
        self.params.update(params)
        return self

    def fit(self, X, y):
        self.encoder_ = LabelEncoder().fit(y)
        self.classes_ = self.encoder_.classes_
        self.model_ = XGBClassifier(**self.params).fit(X, self.encoder_.transform(y))
        return self

    def predict(self, X):
        return self.encoder_.inverse_transform(self.model_.predict(X).astype(int))

    def predict_proba(self, X):
        return self.model_.predict_proba(X)

    @property
    def feature_importances_(self):
        return self.model_.feature_importances_


class Persistencia(BaseEstimator):
    """Referencia: repite lo que hizo el mismo turno/ciclo el día anterior.

    Si no hay dato del día anterior usa la mediana (regresión) o la moda
    (clasificación) de entrenamiento del grupo (p. ej. Turno, n_ciclos, Ciclo).
    Compite en la selección como un modelo más: si ningún modelo de ML la
    supera en validación, se usa ella.
    """

    def __init__(self, columna: str, grupos: tuple[str, ...] = ("Turno",), tarea: str = "regresion"):
        self.columna = columna
        self.grupos = grupos
        self.tarea = tarea

    def fit(self, X, y):
        y = pd.Series(np.asarray(y), index=X.index)
        agregar = (lambda s: s.mode().iloc[0]) if self.tarea == "clasificacion" else "median"
        self.respaldo_ = y.groupby([X[g] for g in self.grupos]).agg(agregar)
        self.global_ = y.mode().iloc[0] if self.tarea == "clasificacion" else float(y.median())
        if self.tarea == "clasificacion":
            self.classes_ = np.sort(y.unique())
        return self

    def predict(self, X):
        indice = pd.MultiIndex.from_frame(X[list(self.grupos)]) if len(self.grupos) > 1 else X[self.grupos[0]]
        respaldo = pd.Series(self.respaldo_.reindex(indice).to_numpy(), index=X.index)
        pred = X[self.columna].astype(float).fillna(respaldo).fillna(self.global_)
        if self.tarea == "clasificacion":
            pred = pred.round().clip(self.classes_.min(), self.classes_.max()).astype(int)
        return pred.to_numpy()


PERSISTENCIA = {
    "n_ciclos": ("prev_n_ciclos", ("Turno",)),
    "riego_m3ha": ("prev_ciclo_m3ha", ("Turno", "n_ciclos", "Ciclo")),
    "inicio_min": ("prev_ciclo_inicio_min", ("Turno", "n_ciclos", "Ciclo")),
}


def _modelo_base(familia: str, tarea: str, params: dict[str, Any], seed: int):
    params = dict(params)
    if "hidden_layer_sizes" in params:
        params["hidden_layer_sizes"] = tuple(params["hidden_layer_sizes"])
    clasif = tarea == "clasificacion"
    if familia == "random_forest":
        cls = RandomForestClassifier if clasif else RandomForestRegressor
        return cls(random_state=seed, n_jobs=-1, **params)
    if familia == "xgboost":
        params.setdefault("tree_method", "hist")
        if clasif:
            return XGBEtiquetado(random_state=seed, n_jobs=-1, **params)
        return XGBRegressor(random_state=seed, n_jobs=-1, **params)
    if familia == "svr":
        return SVC(random_state=seed, **params) if clasif else SVR(**params)
    if familia == "mlp":
        params.setdefault("early_stopping", True)
        params.setdefault("n_iter_no_change", 20)
        cls = MLPClassifier if clasif else MLPRegressor
        return cls(random_state=seed, **params)
    raise ValueError(f"Familia de modelo no soportada: {familia}")


def _preprocesador(categoricas: list[str], numericas: list[str], escalar: bool) -> ColumnTransformer:
    pasos_num = [("imputar", SimpleImputer(strategy="median", add_indicator=True))]
    if escalar:
        pasos_num.append(("escalar", StandardScaler()))
    transformadores = [("num", Pipeline(pasos_num), numericas)]
    if categoricas:
        transformadores.append(
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), categoricas)
        )
    return ColumnTransformer(transformadores, remainder="drop", verbose_feature_names_out=False)


def crear_estimador(
    familia: str,
    tarea: str,
    params: dict[str, Any],
    categoricas: list[str],
    numericas: list[str],
    seed: int = 42,
):
    """Pipeline listo para ``fit(X_dataframe, y)``."""
    escalar = familia in ESCALAN
    pipe = Pipeline(
        [
            ("prep", _preprocesador(categoricas, numericas, escalar)),
            ("modelo", _modelo_base(familia, tarea, params, seed)),
        ]
    )
    if tarea == "regresion" and escalar:
        # SVR y MLP aprenden mejor con el target estandarizado.
        return TransformedTargetRegressor(regressor=pipe, transformer=StandardScaler())
    return pipe


def prefijo_params(estimador) -> str:
    return "regressor__modelo__" if isinstance(estimador, TransformedTargetRegressor) else "modelo__"


def espacio_busqueda(familia: str, tarea: str) -> dict[str, list]:
    """Espacios para RandomizedSearchCV (sin prefijo)."""
    if familia == "random_forest":
        return {
            "n_estimators": [200, 300, 500],
            "max_depth": [8, 12, 18, None],
            "min_samples_leaf": [2, 5, 10, 20],
            "max_features": ["sqrt", 0.3, 0.5, 0.8],
        }
    if familia == "xgboost":
        return {
            "n_estimators": [200, 400, 700],
            "max_depth": [3, 4, 5, 6],
            "learning_rate": [0.02, 0.05, 0.1],
            "subsample": [0.7, 0.85, 1.0],
            "colsample_bytree": [0.5, 0.7, 0.9],
            "min_child_weight": [1, 3, 10],
        }
    if familia == "svr":
        espacio = {"C": [0.3, 1, 3, 10, 30], "gamma": ["scale", 0.003, 0.01, 0.03]}
        if tarea == "regresion":
            espacio["epsilon"] = [0.05, 0.1, 0.2]
        return espacio
    if familia == "mlp":
        return {
            "hidden_layer_sizes": [(32,), (64, 32), (128, 64), (64, 64, 32)],
            "alpha": [1e-4, 1e-3, 1e-2, 1e-1],
            "learning_rate_init": [3e-4, 1e-3, 3e-3],
        }
    raise ValueError(familia)


def importancias(estimador) -> dict[str, float]:
    """Importancia de variables si el modelo la expone (árboles)."""
    if isinstance(estimador, Persistencia):
        return {}
    pipe = estimador.regressor_ if isinstance(estimador, TransformedTargetRegressor) else estimador
    modelo = pipe.named_steps["modelo"]
    if not hasattr(modelo, "feature_importances_"):
        return {}
    nombres = list(pipe.named_steps["prep"].get_feature_names_out())
    valores = np.asarray(modelo.feature_importances_, dtype=float)
    return dict(sorted(zip(nombres, valores), key=lambda kv: -kv[1]))
