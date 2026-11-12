"""Experimento A: número de ciclos por turno y día."""

from __future__ import annotations

import numpy as np
import pandas as pd

from candidatos import (
    CambioSeguro,
    DeltaCiclos,
    DosEtapas,
    Fabrica,
    PesoReciente,
    VotoProba,
    referencia,
)
from comun import Candidato, Datos, Periodo, correr, mascara_eval, metricas_n_ciclos
from riego_ml.modeling.especiales import TransicionNCiclos

TARGET = "n_ciclos"
CLAVE, MAYOR_MEJOR = "accuracy", True
METRICAS = ["accuracy", "accuracy_pm1", "acierto_sin_cambio", "acierto_con_cambio", "propone_cambio",
            "precision_cambio", "acierto_4mas", "f1_macro", "cohen_kappa", "mae_ciclos"]


def registro(d: Datos) -> list[Candidato]:
    fab = Fabrica(d.config, d.categoricas)
    f = d.f_turno
    C = "clasificacion"

    def ml(familia, **extra):
        return lambda: fab.ml(familia, C, f, **extra)

    def voto():
        return VotoProba([fab.ml("random_forest", C, f), fab.ml("xgboost", C, f), fab.ml("lightgbm", C, f),
                          fab.ml("catboost", C, f)])

    lista = [
        Candidato("actual (repetir ayer salvo cambio seguro LGBM)", lambda: fab.persistencia_segura(f),
                  "El modelo en uso, con la misma receta"),
        Candidato("repetir ayer", lambda: referencia("prev_n_ciclos", ("Turno",), C), "Copia el n° de ayer"),
        Candidato("promedio 7 días", lambda: referencia("n_ciclos_media7", ("Turno",), C),
                  "Promedio de los últimos 7 días, redondeado"),
        Candidato("semana pasada", lambda: referencia("n_ciclos_d7", ("Turno",), C),
                  "Lo del mismo día de la semana pasada"),
        Candidato("transición (Markov)", TransicionNCiclos, "P(hoy | ayer, mes)"),
        Candidato("Random Forest", ml("random_forest"), "Votación de 300 árboles", clave="rf"),
        Candidato("XGBoost", ml("xgboost"), "400 árboles en fila (boosting)", clave="xgb"),
        Candidato("LightGBM", ml("lightgbm"), "400 árboles en fila (boosting)", clave="lgbm"),
        Candidato("CatBoost", ml("catboost"), "600 árboles en fila (boosting)", clave="cat"),
        Candidato("Extra Trees", lambda: fab.sk("extratrees", C, f), "Bosque de árboles más aleatorios"),
        Candidato("HistGradientBoosting", lambda: fab.sk("histgb", C, f), "Boosting de scikit-learn"),
        Candidato("Regresión logística", lambda: fab.sk("logistica", C, f), "Modelo lineal (no árboles)"),
        Candidato("Random Forest peso reciente", lambda: PesoReciente(fab.ml("random_forest", C, f), 365),
                  "RF que da el doble de peso a lo del último año"),
        Candidato("LightGBM peso reciente", lambda: PesoReciente(fab.ml("lightgbm", C, f), 365),
                  "LightGBM que da el doble de peso a lo del último año"),
        Candidato("Votación RF+XGB+LGBM+CatBoost", voto, "Promedio de probabilidades de 4 modelos", clave="voto"),
    ]
    # Repetir ayer salvo cambio seguro, con otros modelos base y umbrales reales
    bases = {"rf": ml("random_forest"), "cat": ml("catboost"), "lgbm": ml("lightgbm"), "voto": voto}
    nombres = {"rf": "RF", "cat": "CatBoost", "lgbm": "LightGBM", "voto": "Votación"}
    for b, crear_base in bases.items():
        for u in (0.5, 0.6, 0.7, 0.8):
            lista.append(Candidato(
                f"cambio seguro {nombres[b]} ≥{int(u * 100)}%",
                (lambda cb=crear_base, uu=u: CambioSeguro(cb(), uu)),
                f"Repite ayer salvo que {nombres[b]} esté ≥{int(u * 100)}% seguro de otro n°",
                clave=f"cs_{b}", ajustes={"umbral": u}))
    # Predecir el CAMBIO respecto de ayer (-2..+2)
    for b, crear_base in {"lgbm": ml("lightgbm"), "rf": ml("random_forest")}.items():
        for u in (0.0, 0.5, 0.6, 0.7):
            lista.append(Candidato(
                f"delta {nombres[b]}" + (f" ≥{int(u * 100)}%" if u else ""),
                (lambda cb=crear_base: DeltaCiclos(cb(), fab.ml("lightgbm", C, f), 0.0)),
                f"Predice cuánto sube/baja respecto de ayer ({nombres[b]})",
                clave=f"delta_{b}", ajustes={"umbral": u}))
    # Dos etapas: ¿cambia? + ¿a cuánto?
    for b, crear_base in {"lgbm": ml("lightgbm"), "rf": ml("random_forest")}.items():
        for u in (0.4, 0.5, 0.6, 0.7):
            lista.append(Candidato(
                f"dos etapas {nombres[b]} ≥{int(u * 100)}%",
                (lambda cb=crear_base: DosEtapas(cb(), fab.ml("lightgbm", C, f), 0.5)),
                f"1) ¿cambia hoy? ({nombres[b]})  2) ¿a cuánto?", clave=f"dos_{b}", ajustes={"umbral": u}))
    return lista


def preparador(d: Datos):
    td = d.turno_dia

    def preparar(p: Periodo):
        tr, ev = p.mascaras(td["Fecha"])
        ev &= mascara_eval(td)
        return td[tr], td.loc[tr, "n_ciclos_clase"], td[ev], td.loc[ev, "n_ciclos_clase"]

    return preparar


def medir(y, pred, X) -> dict[str, float]:
    return metricas_n_ciclos(y, pred, X["prev_n_ciclos"])


def ejecutar(d: Datos, lista_periodos, log) -> tuple[pd.DataFrame, dict[str, np.ndarray], list[Candidato]]:
    reg = registro(d)
    res, pred = correr(reg, preparador(d), medir, lista_periodos, log, TARGET)
    return res, pred, reg
