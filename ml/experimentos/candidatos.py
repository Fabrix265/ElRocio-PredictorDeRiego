"""Modelos candidatos de los experimentos.

Todos reciben el DataFrame completo (con claves y todas las columnas) y eligen
internamente sus columnas: los ``Pipeline`` de ``riego_ml`` ya lo hacen (el
``ColumnTransformer`` descarta el resto). Ninguno cambia el código de ``riego_ml``:
lo reutilizan o lo envuelven.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.ensemble import (
    ExtraTreesClassifier,
    ExtraTreesRegressor,
    HistGradientBoostingClassifier,
    HistGradientBoostingRegressor,
)
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import Pipeline

from comun import MAX_CICLOS, SEED, ajustar, franja
from riego_ml.modeling.especiales import Persistencia, PersistenciaSegura, RangoCuantiles
from riego_ml.modeling.estimadores import _preprocesador, crear_estimador

CLAVES = ["Fecha", "Fundo", "Modulo", "Turno"]


# --------------------------------------------------------------------------- #
# Fábricas de modelos base
# --------------------------------------------------------------------------- #
class Fabrica:
    """Crea estimadores con las features y parámetros del pipeline en uso."""

    def __init__(self, config, categoricas: list[str]):
        self.config = config
        self.categoricas = categoricas

    def params(self, familia: str, tarea: str) -> dict[str, Any]:
        m = self.config.modelos[familia]
        return dict(m.clasificacion if tarea == "clasificacion" else m.regresion)

    def num(self, features: list[str]) -> list[str]:
        return [c for c in features if c not in self.categoricas]

    def ml(self, familia: str, tarea: str, features: list[str], **extra) -> Pipeline:
        """RF / XGBoost / LightGBM / CatBoost del pipeline en uso (parámetros del YAML + ``extra``)."""
        params = {**self.params(familia, tarea), **extra}
        return crear_estimador(familia, tarea, params, self.categoricas, self.num(features), SEED)

    def sk(self, nombre: str, tarea: str, features: list[str]) -> Pipeline:
        """Modelos de scikit-learn que el pipeline en uso no tiene."""
        clasif = tarea == "clasificacion"
        escalar = nombre in ("logistica", "ridge")
        if nombre == "extratrees":
            cls = ExtraTreesClassifier if clasif else ExtraTreesRegressor
            extra = {"class_weight": "balanced_subsample"} if clasif else {"max_depth": 20}
            modelo = cls(n_estimators=400, min_samples_leaf=3, max_features=0.5, n_jobs=-1, random_state=SEED,
                         **extra)
        elif nombre == "histgb":
            cls = HistGradientBoostingClassifier if clasif else HistGradientBoostingRegressor
            extra = {"class_weight": "balanced"} if clasif else {}
            modelo = cls(max_iter=400, learning_rate=0.05, max_leaf_nodes=31, l2_regularization=1.0,
                         random_state=SEED, **extra)
        elif nombre == "logistica":
            modelo = LogisticRegression(C=0.5, max_iter=2000, class_weight="balanced")
        elif nombre == "ridge":
            modelo = Ridge(alpha=10.0)
        else:
            raise ValueError(nombre)
        return Pipeline([("prep", _preprocesador(self.categoricas, self.num(features), escalar)),
                         ("modelo", modelo)])

    def persistencia_segura(self, features: list[str]) -> PersistenciaSegura:
        """El modelo de n° de ciclos en uso, tal cual."""
        return PersistenciaSegura(self.categoricas, self.num(features), self.params("lightgbm", "clasificacion"),
                                  SEED)

    def rango(self, features: list[str]) -> RangoCuantiles:
        r = self.config.rangos
        return RangoCuantiles(self.categoricas, self.num(features), r.inferior, r.superior, SEED)


def referencia(columna: str, grupos: tuple[str, ...], tarea: str) -> Persistencia:
    return Persistencia(columna, grupos, tarea)


# --------------------------------------------------------------------------- #
# Envoltorios generales
# --------------------------------------------------------------------------- #
class PesoReciente(BaseEstimator):
    """Entrena dando más peso a lo reciente: peso = 0.5 ** (antigüedad / vida_media)."""

    def __init__(self, base, vida_media_dias: float = 365.0):
        self.base = base
        self.vida_media_dias = vida_media_dias

    def fit(self, X, y):
        edad = (X["Fecha"].max() - X["Fecha"]).dt.days.to_numpy(float)
        peso = 0.5 ** (edad / self.vida_media_dias)
        self.base_ = ajustar(self.base, X, y, modelo__sample_weight=peso)
        if hasattr(self.base_, "classes_"):
            self.classes_ = self.base_.classes_
        return self

    def predict(self, X):
        return self.base_.predict(X)

    def predict_proba(self, X):
        return self.base_.predict_proba(X)


class VentanaReciente(BaseEstimator):
    """Aprende solo con los últimos ``dias`` (descarta la historia antigua)."""

    def __init__(self, base, dias: int = 730):
        self.base = base
        self.dias = dias

    def fit(self, X, y):
        m = (X["Fecha"] >= X["Fecha"].max() - pd.Timedelta(days=self.dias)).to_numpy()
        self.base_ = ajustar(self.base, X[m], np.asarray(y)[m])
        if hasattr(self.base_, "classes_"):
            self.classes_ = self.base_.classes_
        return self

    def predict(self, X):
        return self.base_.predict(X)

    def predict_proba(self, X):
        return self.base_.predict_proba(X)


class Promedio(BaseEstimator):
    """Ensamble: promedio de las predicciones de varios regresores ya creados."""

    def __init__(self, bases: list):
        self.bases = bases

    def fit(self, X, y):
        self.bases_ = [ajustar(b, X, y) for b in self.bases]
        return self

    def predict(self, X):
        return np.mean([b.predict(X) for b in self.bases_], axis=0)


class Ajustado(BaseEstimator):
    """Envuelve un estimador YA entrenado (para reutilizarlo entre candidatos)."""

    def __init__(self, entrenado):
        self.entrenado = entrenado

    def fit(self, X, y):
        return self

    def predict(self, X):
        return self.entrenado.predict(X)

    def predict_proba(self, X):
        return self.entrenado.predict_proba(X)

    @property
    def classes_(self):
        return self.entrenado.classes_


class Residual(BaseEstimator):
    """Aprende la diferencia con una referencia (p. ej. la media de 7 días) y la suma.

    Los árboles no extrapolan: aprender "cuánto se aparta hoy de lo habitual" suele
    generalizar mejor cuando el nivel cambia entre temporadas.
    """

    def __init__(self, base, columna: str, grupos: tuple[str, ...] = ("Turno", "n_ciclos", "Ciclo")):
        self.base = base
        self.columna = columna
        self.grupos = grupos

    def _ref(self, X) -> np.ndarray:
        idx = pd.MultiIndex.from_frame(X[list(self.grupos)])
        respaldo = pd.Series(self.respaldo_.reindex(idx).to_numpy(), index=X.index)
        return X[self.columna].astype(float).fillna(respaldo).fillna(self.global_).to_numpy()

    def fit(self, X, y):
        y = pd.Series(np.asarray(y, float), index=X.index)
        self.respaldo_ = y.groupby([X[g] for g in self.grupos]).median()
        self.global_ = float(y.median())
        self.base_ = ajustar(self.base, X, y.to_numpy() - self._ref(X))
        return self

    def predict(self, X):
        return self._ref(X) + self.base_.predict(X)


class RepetirSalvoCambio(BaseEstimator):
    """Repite lo de ayer de ese ciclo salvo que el modelo se aparte más de ``umbral``.

    Las dosis se programan y se repiten muchos días seguidos: copiar ayer acierta
    exacto la mayoría de las veces, pero falla fuerte cuando la dosis cambia. Este
    híbrido usa el modelo solo cuando ve un cambio claro. Sin dato de ayer, usa el modelo.
    """

    def __init__(self, base, columna: str, umbral: float = 3.0):
        self.base = base
        self.columna = columna
        self.umbral = umbral

    def fit(self, X, y):
        self.base_ = ajustar(self.base, X, y)
        return self

    def predict(self, X):
        modelo = np.asarray(self.base_.predict(X), float)
        ayer = X[self.columna].to_numpy(float)
        usar_modelo = np.isnan(ayer) | (np.abs(modelo - np.nan_to_num(ayer)) > self.umbral)
        return np.where(usar_modelo, modelo, ayer)


# --------------------------------------------------------------------------- #
# N° de ciclos
# --------------------------------------------------------------------------- #
def _prev(X) -> np.ndarray:
    return X["prev_n_ciclos"].clip(1, MAX_CICLOS).round().to_numpy(float)


class CambioSeguro(BaseEstimator):
    """Repite lo de ayer salvo que ``base`` esté al menos ``umbral`` seguro de otro número.

    Es la misma idea del modelo en uso, pero con otro modelo base y un umbral fijo
    (el modelo en uso eligió el umbral con un solo período y quedó en "nunca cambiar").
    """

    def __init__(self, base, umbral: float = 0.6):
        self.base = base
        self.umbral = umbral

    def fit(self, X, y):
        self.base_ = ajustar(self.base, X, y)
        self.classes_ = np.asarray(self.base_.classes_)
        return self

    def predict(self, X):
        proba = self.base_.predict_proba(X)
        mejor = self.classes_[np.argmax(proba, axis=1)].astype(float)
        conf = proba.max(axis=1)
        prev = _prev(X)
        cambiar = np.isnan(prev) | ((mejor != prev) & (conf >= self.umbral))
        return np.where(cambiar, mejor, prev).astype(int)


class VotoProba(BaseEstimator):
    """Ensamble de clasificadores: promedia sus probabilidades."""

    def __init__(self, bases: list):
        self.bases = bases

    def fit(self, X, y):
        self.bases_ = [ajustar(b, X, y) for b in self.bases]
        self.classes_ = np.asarray(self.bases_[0].classes_)
        return self

    def predict_proba(self, X):
        out = np.zeros((len(X), len(self.classes_)))
        for b in self.bases_:
            p = b.predict_proba(X)
            cl = list(np.asarray(b.classes_))
            for j, c in enumerate(self.classes_):
                if c in cl:
                    out[:, j] += p[:, cl.index(c)]
        return out / len(self.bases_)

    def predict(self, X):
        return self.classes_[np.argmax(self.predict_proba(X), axis=1)]


class DeltaCiclos(BaseEstimator):
    """Predice el CAMBIO respecto de ayer (-2..+2) y lo suma a los ciclos de ayer.

    ``umbral``: solo cambia si la probabilidad del cambio elegido supera ese valor.
    Sin dato de ayer usa ``respaldo`` (un clasificador directo).
    """

    def __init__(self, base, respaldo, umbral: float = 0.0):
        self.base = base
        self.respaldo = respaldo
        self.umbral = umbral

    def fit(self, X, y):
        y = np.asarray(y).astype(int)
        prev = _prev(X)
        ok = ~np.isnan(prev)
        delta = np.clip(y[ok] - prev[ok], -2, 2).astype(int)
        self.base_ = ajustar(self.base, X[ok], delta)
        self.respaldo_ = ajustar(self.respaldo, X, y)
        self.classes_ = np.arange(1, MAX_CICLOS + 1)
        return self

    def predict(self, X):
        prev = _prev(X)
        proba = self.base_.predict_proba(X)
        deltas = np.asarray(self.base_.classes_)
        # Solo deltas que dejan un n° válido
        validos = np.clip(np.nan_to_num(prev)[:, None] + deltas[None, :], 1, MAX_CICLOS) == (
            np.nan_to_num(prev)[:, None] + deltas[None, :])
        proba = np.where(validos, proba, 0.0)
        mejor = deltas[np.argmax(proba, axis=1)]
        conf = proba.max(axis=1)
        delta = np.where((mejor != 0) & (conf >= self.umbral), mejor, 0)
        pred = prev + delta
        sin_prev = np.isnan(prev)
        if sin_prev.any():
            pred[sin_prev] = self.respaldo_.predict(X[sin_prev])
        return np.clip(pred, 1, MAX_CICLOS).astype(int)


class DosEtapas(BaseEstimator):
    """1) ¿hoy cambia el n° de ciclos? (sí/no)  2) si cambia, ¿a cuánto? (el más probable ≠ ayer)."""

    def __init__(self, detector, destino, umbral: float = 0.5):
        self.detector = detector
        self.destino = destino
        self.umbral = umbral

    def fit(self, X, y):
        y = np.asarray(y).astype(int)
        prev = _prev(X)
        ok = ~np.isnan(prev)
        cambia = (y[ok] != prev[ok]).astype(int)
        self.detector_ = ajustar(self.detector, X[ok], cambia)
        self.destino_ = ajustar(self.destino, X, y)
        self.classes_ = np.asarray(self.destino_.classes_)
        return self

    def prob_cambio(self, X) -> np.ndarray:
        return self.detector_.predict_proba(X)[:, 1]

    def predict(self, X):
        prev = _prev(X)
        p_cambio = self.prob_cambio(X)
        proba = self.destino_.predict_proba(X).copy()
        # el destino nunca es el mismo n° de ayer
        for j, c in enumerate(self.classes_):
            proba[prev == c, j] = -1
        destino = self.classes_[np.argmax(proba, axis=1)]
        directo = self.destino_.predict(X)
        pred = np.where(p_cambio >= self.umbral, destino, prev)
        pred = np.where(np.isnan(prev), directo, pred)
        return pred.astype(int)


# --------------------------------------------------------------------------- #
# Hora de inicio
# --------------------------------------------------------------------------- #
class InicioEstructural(BaseEstimator):
    """Arma el horario en dos partes en vez de predecir cada hora suelta.

    * ``modelo_primero``: hora de inicio del 1er ciclo del turno.
    * ``modelo_desfase``: cuántos minutos después del 1er ciclo arranca el ciclo k (k >= 2).
    Inicio del ciclo k = inicio del 1er ciclo + desfase.
    Con ``primero_conocido=True`` se usa la hora REAL del 1er ciclo (escenario: el
    operador la indica y el sistema completa el resto).
    """

    def __init__(self, modelo_primero, modelo_desfase, primero_conocido: bool = False):
        self.modelo_primero = modelo_primero
        self.modelo_desfase = modelo_desfase
        self.primero_conocido = primero_conocido

    def fit(self, X, y):
        y = np.asarray(y, float)
        uno = (X["Ciclo"] == 1).to_numpy()
        self.primero_ = ajustar(self.modelo_primero, X[uno], y[uno])
        desfase = y - X["inicio_ciclo1_real"].to_numpy(float)
        resto = ~uno & np.isfinite(desfase)
        self.desfase_ = ajustar(self.modelo_desfase, X[resto], desfase[resto])
        return self

    def predict(self, X):
        uno = (X["Ciclo"] == 1).to_numpy()
        if self.primero_conocido:
            primero = X["inicio_ciclo1_real"].to_numpy(float)
        else:
            p1 = pd.Series(self.primero_.predict(X[uno]), index=X.index[uno])
            claves = pd.MultiIndex.from_frame(X[CLAVES])
            mapa = pd.Series(p1.to_numpy(), index=claves[uno])
            mapa = mapa[~mapa.index.duplicated()]
            primero = mapa.reindex(claves).to_numpy(float)
            # Si un turno-día no trae su ciclo 1 (no debería pasar), se predice directo
            faltan = np.isnan(primero)
            if faltan.any():
                primero[faltan] = self.primero_.predict(X[faltan])
        desfase = np.where(uno, 0.0, self.desfase_.predict(X))
        return np.clip(primero + np.maximum(desfase, 0.0), 0, 1439)


class RestriccionHoraria(BaseEstimator):
    """Corre las horas que caen en franjas casi nunca usadas (< ``minimo`` de los ciclos)
    al borde más cercano de una hora sí usada. Las horas permitidas se aprenden del train."""

    def __init__(self, base, minimo: float = 0.01):
        self.base = base
        self.minimo = minimo

    def fit(self, X, y):
        self.base_ = ajustar(self.base, X, y)
        horas = (np.asarray(y, float) // 60).clip(0, 23).astype(int)
        frec = np.bincount(horas, minlength=24) / len(horas)
        self.permitidas_ = np.flatnonzero(frec >= self.minimo)
        return self

    def predict(self, X):
        pred = np.asarray(self.base_.predict(X), float)
        horas = (pred // 60).clip(0, 23).astype(int)
        malas = ~np.isin(horas, self.permitidas_)
        if malas.any():
            bordes = np.concatenate([self.permitidas_ * 60.0, self.permitidas_ * 60.0 + 59.0])
            idx = np.abs(pred[malas, None] - bordes[None, :]).argmin(axis=1)
            pred[malas] = bordes[idx]
        return pred


class FranjaClasificador(BaseEstimator):
    """Predice solo la franja del día (00-06, 06-12, 12-18, 18-24). Devuelve el centro de la franja."""

    def __init__(self, base):
        self.base = base

    def fit(self, X, y):
        self.base_ = ajustar(self.base, X, franja(y))
        return self

    def predict_franja(self, X) -> np.ndarray:
        return np.asarray(self.base_.predict(X)).astype(int)

    def predict(self, X):
        return self.predict_franja(X) * 360.0 + 180.0


# --------------------------------------------------------------------------- #
# Rangos
# --------------------------------------------------------------------------- #
def margen_conformal(puntaje: np.ndarray, nivel: float) -> float:
    puntaje = np.asarray(puntaje, float)
    puntaje = puntaje[np.isfinite(puntaje)]
    if puntaje.size == 0:
        return 0.0
    q = min(1.0, nivel * (1 + 1 / puntaje.size))
    return float(max(0.0, np.quantile(puntaje, q)))


def margen_movil(fechas: pd.Series, puntaje: np.ndarray, fechas_objetivo: pd.Series, dias: int, nivel: float,
                 respaldo: float, min_dias: int = 14) -> np.ndarray:
    """Margen recalculado cada día con los ``dias`` anteriores ya observados (sin mirar el día objetivo)."""
    df = pd.DataFrame({"Fecha": pd.to_datetime(fechas).to_numpy(), "p": np.asarray(puntaje, float)})
    df = df[np.isfinite(df["p"])]
    por_dia = {f: g["p"].to_numpy() for f, g in df.groupby("Fecha")}
    dias_ordenados = np.array(sorted(por_dia))
    cache: dict[pd.Timestamp, float] = {}
    out = np.empty(len(fechas_objetivo))
    for i, f in enumerate(pd.to_datetime(fechas_objetivo)):
        if f not in cache:
            sel = dias_ordenados[(dias_ordenados < np.datetime64(f)) &
                                 (dias_ordenados >= np.datetime64(f - pd.Timedelta(days=dias)))]
            if len(sel) < min_dias:
                cache[f] = respaldo
            else:
                cache[f] = margen_conformal(np.concatenate([por_dia[d] for d in sel]), nivel)
        out[i] = cache[f]
    return out


FabricaT = Callable[[], Any]
