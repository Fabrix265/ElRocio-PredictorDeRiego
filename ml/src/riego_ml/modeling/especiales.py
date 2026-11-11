"""Modelos específicos del problema y referencias simples.

Referencias (no aprenden, solo repiten):
* ``persistencia``   lo que hizo el mismo turno/ciclo ayer.
* ``media_7d``       el promedio de los últimos 7 días.
* ``semana_pasada``  lo que se hizo el mismo día de la semana pasada.

Número de ciclos:
* ``transicion``     tabla de transición tipo Markov: P(ciclos hoy | ciclos
  ayer, mes). Extiende la persistencia en vez de competir con ella.
* ``ordinal``        regresión logística ordinal (1 < 2 < 3 ...): equivocarse
  por un ciclo cuesta menos que por tres.
* ``persistencia_segura``  repite lo de ayer y solo cambia cuando un modelo
  LightGBM está muy seguro (umbral elegido con datos de entrenamiento).

m3/ha:
* ``dosis``          clasifica entre las dosis programadas habituales
  (15, 20, 30, 35 m3/ha...) en vez de predecir un número libre.

Rangos:
* ``RangoCuantiles`` dos LightGBM por cuantiles (p10 y p90) que dan el
  intervalo "casi seguro" alrededor de la predicción.

Todos exponen ``columnas_requeridas`` para que el entrenamiento les pase las
columnas que usan aunque no estén en la lista de features del modelo.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin, RegressorMixin
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.pipeline import Pipeline

from riego_ml.modeling.estimadores import _preprocesador, crear_estimador

REFERENCIAS = {
    "n_ciclos": {
        "persistencia": ("prev_n_ciclos", ("Turno",)),
        "media_7d": ("n_ciclos_media7", ("Turno",)),
        "semana_pasada": ("n_ciclos_d7", ("Turno",)),
    },
    "riego_m3ha": {
        "persistencia": ("prev_ciclo_m3ha", ("Turno", "n_ciclos", "Ciclo")),
        "media_7d": ("ciclo_m3ha_media7", ("Turno", "n_ciclos", "Ciclo")),
        "semana_pasada": ("ciclo_m3ha_d7", ("Turno", "n_ciclos", "Ciclo")),
    },
    "inicio_min": {
        "persistencia": ("prev_ciclo_inicio_min", ("Turno", "n_ciclos", "Ciclo")),
        "media_7d": ("ciclo_inicio_media7", ("Turno", "n_ciclos", "Ciclo")),
        "semana_pasada": ("ciclo_inicio_d7", ("Turno", "n_ciclos", "Ciclo")),
    },
}


class Persistencia(BaseEstimator):
    """Repite el valor de ``columna`` (ayer, media 7 días, semana pasada...).

    Si falta, usa la mediana (regresión) o la moda (clasificación) de
    entrenamiento del grupo (p. ej. Turno, n_ciclos, Ciclo).
    """

    def __init__(self, columna: str, grupos: tuple[str, ...] = ("Turno",), tarea: str = "regresion"):
        self.columna = columna
        self.grupos = grupos
        self.tarea = tarea

    @property
    def columnas_requeridas(self) -> list[str]:
        return [self.columna, *self.grupos]

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


class TransicionNCiclos(BaseEstimator, ClassifierMixin):
    """P(ciclos hoy | ciclos ayer, mes) con suavizado y respaldo a P(hoy | ayer)."""

    def __init__(self, suavizado: float = 1.0, min_casos_mes: int = 15):
        self.suavizado = suavizado
        self.min_casos_mes = min_casos_mes

    columnas_requeridas = ["prev_n_ciclos", "mes", "Turno"]

    def fit(self, X, y):
        y = pd.Series(np.asarray(y).astype(int), index=X.index)
        self.classes_ = np.sort(y.unique())
        maxc = self.classes_.max()
        prev = X["prev_n_ciclos"].clip(upper=maxc)
        datos = pd.DataFrame({"prev": prev, "mes": X["mes"], "y": y}).dropna()
        self.tabla_mes_ = pd.crosstab([datos["prev"], datos["mes"]], datos["y"]).reindex(
            columns=self.classes_, fill_value=0)
        self.tabla_ = pd.crosstab(datos["prev"], datos["y"]).reindex(columns=self.classes_, fill_value=0)
        self.moda_turno_ = y.groupby(X["Turno"]).agg(lambda s: s.mode().iloc[0])
        self.global_ = int(y.mode().iloc[0])
        return self

    def predict_proba(self, X):
        maxc = self.classes_.max()
        filas = []
        for prev, mes, turno in zip(X["prev_n_ciclos"].clip(upper=maxc), X["mes"], X["Turno"]):
            if pd.isna(prev):
                fila = np.zeros(len(self.classes_))
                moda = self.moda_turno_.get(turno, self.global_)
                fila[np.searchsorted(self.classes_, moda)] = 1.0
                filas.append(fila)
                continue
            base = self.tabla_.loc[prev].to_numpy(float) if prev in self.tabla_.index else np.zeros(len(self.classes_))
            clave = (prev, mes)
            if clave in self.tabla_mes_.index and self.tabla_mes_.loc[clave].sum() >= self.min_casos_mes:
                conteo = self.tabla_mes_.loc[clave].to_numpy(float)
            else:
                conteo = base
            conteo = conteo + self.suavizado * (base / base.sum() if base.sum() else 1.0 / len(base))
            filas.append(conteo / conteo.sum())
        return np.vstack(filas)

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


class OrdinalLogistico(BaseEstimator, ClassifierMixin):
    """Regresión logística ordinal (método de Frank & Hall).

    Ajusta un clasificador binario por cada umbral "¿más de k ciclos?" y arma
    la probabilidad de cada clase como diferencia de acumuladas.
    """

    def __init__(self, categoricas: list[str] | None = None, numericas: list[str] | None = None, C: float = 0.5):
        self.categoricas = categoricas
        self.numericas = numericas
        self.C = C

    def fit(self, X, y):
        y = np.asarray(y).astype(int)
        self.classes_ = np.sort(np.unique(y))
        self.prep_ = _preprocesador(self.categoricas or [], self.numericas or [], escalar=True).fit(X)
        Z = self.prep_.transform(X)
        self.modelos_ = []
        for k in self.classes_[:-1]:
            objetivo = (y > k).astype(int)
            modelo = LogisticRegression(C=self.C, max_iter=2000) if 0 < objetivo.mean() < 1 else None
            self.modelos_.append((modelo.fit(Z, objetivo) if modelo else objetivo.mean()))
        return self

    def predict_proba(self, X):
        Z = self.prep_.transform(X)
        mayores = [m.predict_proba(Z)[:, 1] if hasattr(m, "predict_proba") else np.full(len(Z), m)
                   for m in self.modelos_]
        acumuladas = np.column_stack([np.ones(len(Z)), *mayores, np.zeros(len(Z))])
        acumuladas = np.minimum.accumulate(acumuladas, axis=1)  # monótonas
        return np.clip(acumuladas[:, :-1] - acumuladas[:, 1:], 0, None)

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


class PersistenciaSegura(BaseEstimator, ClassifierMixin):
    """Repite los ciclos de ayer salvo que LightGBM esté muy seguro de un cambio."""

    UMBRALES = (0.5, 0.6, 0.7, 0.8, 0.9, 1.01)

    def __init__(self, categoricas: list[str] | None = None, numericas: list[str] | None = None,
                 params: dict[str, Any] | None = None, seed: int = 42):
        self.categoricas = categoricas
        self.numericas = numericas
        self.params = params
        self.seed = seed

    def _base(self):
        return crear_estimador("lightgbm", "clasificacion", self.params or {}, self.categoricas or [],
                               self.numericas or [], self.seed)

    def _combinar(self, X, proba, clases, umbral):
        mejor = clases[np.argmax(proba, axis=1)]
        confianza = proba.max(axis=1)
        prev = X["prev_n_ciclos"].clip(clases.min(), clases.max()).round().to_numpy()
        cambiar = np.isnan(prev) | ((mejor != prev) & (confianza >= umbral))
        return np.where(cambiar, mejor, prev).astype(int)

    def fit(self, X, y):
        y = np.asarray(y).astype(int)
        corte = int(len(X) * 0.8)  # las filas vienen ordenadas por fecha
        base = self._base().fit(X.iloc[:corte], y[:corte])
        proba = base.predict_proba(X.iloc[corte:])
        clases = base.classes_
        puntajes = {
            u: f1_score(y[corte:], self._combinar(X.iloc[corte:], proba, clases, u), average="macro")
            for u in self.UMBRALES
        }
        self.umbral_ = max(puntajes, key=puntajes.get)
        self.base_ = self._base().fit(X, y)
        self.classes_ = self.base_.classes_
        return self

    def predict(self, X):
        return self._combinar(X, self.base_.predict_proba(X), self.classes_, self.umbral_)


class ClasificadorDosis(BaseEstimator, RegressorMixin):
    """Predice la dosis (m3/ha) eligiendo entre las dosis programadas habituales."""

    def __init__(self, categoricas: list[str] | None = None, numericas: list[str] | None = None,
                 params: dict[str, Any] | None = None, min_casos: int = 30, seed: int = 42):
        self.categoricas = categoricas
        self.numericas = numericas
        self.params = params
        self.min_casos = min_casos
        self.seed = seed

    def _a_dosis(self, y) -> np.ndarray:
        y = np.asarray(y, dtype=float)
        return self.dosis_[np.abs(y[:, None] - self.dosis_[None, :]).argmin(axis=1)]

    def fit(self, X, y):
        redondeado = pd.Series(np.round(np.asarray(y, dtype=float)))
        conteo = redondeado.value_counts()
        self.dosis_ = np.sort(conteo[conteo >= self.min_casos].index.to_numpy(dtype=float))
        clases = self._a_dosis(y)
        self.base_ = crear_estimador("lightgbm", "clasificacion", self.params or {}, self.categoricas or [],
                                     self.numericas or [], self.seed).fit(X, clases.astype(str))
        return self

    def predict(self, X):
        return self.base_.predict(X).astype(float)


class RangoCuantiles(BaseEstimator):
    """Intervalo [p_inf, p_sup] con dos LightGBM entrenados por cuantiles.

    ``calibrar`` agrega un margen (conformal) para que el rango cubra en datos
    nuevos el porcentaje esperado: los cuantiles solos suelen quedar angostos
    cuando la operación cambia entre períodos.
    """

    def __init__(self, categoricas: list[str] | None = None, numericas: list[str] | None = None,
                 inferior: float = 0.1, superior: float = 0.9, seed: int = 42):
        self.categoricas = categoricas
        self.numericas = numericas
        self.inferior = inferior
        self.superior = superior
        self.seed = seed

    def _modelo(self, alpha: float) -> Pipeline:
        params = {"objective": "quantile", "alpha": alpha, "n_estimators": 400, "learning_rate": 0.05,
                  "num_leaves": 31, "min_child_samples": 20}
        return crear_estimador("lightgbm", "regresion", params, self.categoricas or [], self.numericas or [],
                               self.seed)

    def fit(self, X, y):
        self.columnas_ = list(X.columns)
        self.margen_ = 0.0
        self.bajo_ = self._modelo(self.inferior).fit(X, y)
        self.alto_ = self._modelo(self.superior).fit(X, y)
        return self

    def _crudo(self, X) -> tuple[np.ndarray, np.ndarray]:
        bajo, alto = self.bajo_.predict(X), self.alto_.predict(X)
        return np.minimum(bajo, alto), np.maximum(bajo, alto)

    def calcular_margen(self, X, y) -> float:
        """Margen para que el rango cubra ``superior - inferior`` en (X, y)."""
        bajo, alto = self._crudo(X)
        y = np.asarray(y, dtype=float)
        puntaje = np.maximum(bajo - y, y - alto)
        nivel = min(1.0, (self.superior - self.inferior) * (1 + 1 / max(len(y), 1)))
        return float(max(0.0, np.quantile(puntaje, nivel)))

    def predict(self, X) -> tuple[np.ndarray, np.ndarray]:
        bajo, alto = self._crudo(X)
        return bajo - self.margen_, alto + self.margen_
