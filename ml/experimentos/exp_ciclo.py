"""Experimentos B y C: hora de inicio y volumen (m3/ha) de cada ciclo, más la duración derivada."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from candidatos import (
    Fabrica,
    FranjaClasificador,
    InicioEstructural,
    PesoReciente,
    Promedio,
    RepetirSalvoCambio,
    Residual,
    RestriccionHoraria,
    VentanaReciente,
    referencia,
)
from comun import (
    Candidato,
    Datos,
    Periodo,
    buscar_hiper,
    correr,
    mascara_eval,
    metricas_inicio,
    metricas_reg,
)
from riego_ml.modeling.estimadores import espacio_busqueda

GRUPOS_CICLO = ("Turno", "n_ciclos", "Ciclo")
METRICAS_INICIO = ["mae", "medae", "rmse", "r2", "mbe", "dentro_1h", "dentro_2h", "franja_ok"]
METRICAS_M3HA = ["mae", "medae", "rmse", "r2", "mbe", "dur_mae", "dur_medae", "dur_rmse", "dur_mbe"]


def preparador(d: Datos, target: str, extra_cols: dict[str, str] | None = None):
    ci = d.ciclos

    def preparar(p: Periodo):
        tr, ev = p.mascaras(ci["Fecha"])
        ev &= mascara_eval(ci)
        Xtr, Xev = ci[tr].copy(), ci[ev].copy()
        # Caudal histórico del train (respaldo cuando falta el de 30 días), como el pipeline en uso
        ratio = (Xtr["duracion_min"] / Xtr["riego_m3ha"]).groupby(Xtr["Turno"]).median()
        Xev["_min_por_m3ha"] = Xev["min_por_m3ha_30d"].fillna(Xev["Turno"].map(ratio))
        return Xtr, Xtr[target], Xev, Xev[target]

    return preparar


def medir_inicio(y, pred, X) -> dict[str, float]:
    return metricas_inicio(y, np.clip(pred, 0, 1439))


def medir_m3ha(y, pred, X) -> dict[str, float]:
    out = metricas_reg(y, pred)
    dur = metricas_reg(X["duracion_min"], np.asarray(pred) * X["_min_por_m3ha"].to_numpy())
    out.update({f"dur_{k}": v for k, v in dur.items() if k in ("mae", "medae", "rmse", "mbe", "r2")})
    return out


def _comunes(fab: Fabrica, f: list[str], target: str, ref_cols: dict[str, str],
             ajustados: dict[str, dict[str, Any]]) -> list[Candidato]:
    R = "regresion"

    def ml(familia, **extra):
        return lambda: fab.ml(familia, R, f, **extra)

    lista = [
        Candidato("repetir ayer", lambda: referencia(ref_cols["ayer"], GRUPOS_CICLO, R),
                  "Lo mismo que ese ciclo ayer"),
        Candidato("promedio 7 días", lambda: referencia(ref_cols["media7"], GRUPOS_CICLO, R),
                  "Promedio de ese ciclo en los últimos 7 días"),
        Candidato("semana pasada", lambda: referencia(ref_cols["d7"], GRUPOS_CICLO, R),
                  "Lo del mismo día de la semana pasada"),
        Candidato("Random Forest", ml("random_forest"), "Votación de 300 árboles"),
        Candidato("XGBoost", ml("xgboost"), "500 árboles en fila"),
        Candidato("LightGBM", ml("lightgbm"), "500 árboles en fila"),
        Candidato("CatBoost", ml("catboost"), "800 árboles en fila"),
        Candidato("Extra Trees", lambda: fab.sk("extratrees", R, f), "Bosque de árboles más aleatorios"),
        Candidato("HistGradientBoosting", lambda: fab.sk("histgb", R, f), "Boosting de scikit-learn"),
        Candidato("Ridge (lineal)", lambda: fab.sk("ridge", R, f), "Modelo lineal (no árboles)"),
        Candidato("LightGBM error absoluto", ml("lightgbm", objective="l1"),
                  "LightGBM que minimiza el error promedio (no el cuadrático)"),
        Candidato("XGBoost error absoluto", ml("xgboost", objective="reg:absoluteerror"),
                  "XGBoost que minimiza el error promedio"),
        Candidato("LightGBM Huber", ml("lightgbm", objective="huber", alpha=2.0 if target == "riego_m3ha" else 60.0),
                  "LightGBM menos sensible a valores atípicos"),
        Candidato("LightGBM peso reciente", lambda: PesoReciente(fab.ml("lightgbm", R, f), 365),
                  "Doble peso a lo del último año"),
        Candidato("XGBoost peso reciente", lambda: PesoReciente(fab.ml("xgboost", R, f), 365),
                  "Doble peso a lo del último año"),
        Candidato("LightGBM últimos 2 años", lambda: VentanaReciente(fab.ml("lightgbm", R, f), 730),
                  "Aprende solo con los últimos 2 años"),
        Candidato("Promedio LGBM+XGB+CatBoost",
                  lambda: Promedio([fab.ml("lightgbm", R, f), fab.ml("xgboost", R, f), fab.ml("catboost", R, f)]),
                  "Promedio de 3 modelos"),
        Candidato("Promedio LGBM+XGB+CatBoost+RF",
                  lambda: Promedio([fab.ml("lightgbm", R, f), fab.ml("xgboost", R, f), fab.ml("catboost", R, f),
                                    fab.ml("random_forest", R, f)]),
                  "Promedio de 4 modelos"),
        Candidato("LightGBM sobre lo habitual", lambda: Residual(fab.ml("lightgbm", R, f), ref_cols["habitual"]),
                  "Aprende cuánto se aparta hoy de lo habitual de ese ciclo"),
        Candidato("XGBoost sobre lo habitual", lambda: Residual(fab.ml("xgboost", R, f), ref_cols["habitual"]),
                  "Aprende cuánto se aparta hoy de lo habitual de ese ciclo"),
    ]
    umbrales = (2.0, 4.0, 6.0) if target == "riego_m3ha" else (30.0, 60.0, 120.0)
    unidad = "m3/ha" if target == "riego_m3ha" else "min"
    bases = {"LightGBM": ml("lightgbm"),
             "LightGBM Huber": ml("lightgbm", objective="huber", alpha=2.0 if target == "riego_m3ha" else 60.0)}
    for nb, crear_base in bases.items():
        for u in umbrales:
            lista.append(Candidato(
                f"repetir ayer salvo cambio > {u:g} {unidad} ({nb})",
                (lambda cb=crear_base: RepetirSalvoCambio(cb(), ref_cols["ayer"])),
                f"Copia lo de ayer salvo que {nb} vea un cambio mayor a {u:g} {unidad}",
                clave=f"rsc_{nb}", ajustes={"umbral": u}))
    for familia, params in ajustados.items():
        nombre = {"lightgbm": "LightGBM", "xgboost": "XGBoost", "catboost": "CatBoost"}[familia]
        lista.append(Candidato(f"{nombre} ajustado", (lambda fa=familia, pa=params: fab.ml(fa, R, f, **pa)),
                               f"{nombre} con parámetros elegidos por búsqueda en los períodos de desarrollo"))
        lista.append(Candidato(f"{nombre} ajustado sobre lo habitual",
                               (lambda fa=familia, pa=params: Residual(fab.ml(fa, R, f, **pa), ref_cols["habitual"])),
                               f"{nombre} ajustado + aprende la diferencia con lo habitual"))
    return lista


def registro_inicio(d: Datos, ajustados) -> list[Candidato]:
    fab = Fabrica(d.config, d.categoricas)
    f = d.f_ciclo
    R = "regresion"
    refs = {"ayer": "prev_ciclo_inicio_min", "media7": "ciclo_inicio_media7", "d7": "ciclo_inicio_d7",
            "habitual": "ciclo_inicio_media7"}
    lista = [Candidato("actual (XGBoost)", lambda: fab.ml("xgboost", R, f), "El modelo en uso")]
    lista += _comunes(fab, f, "inicio_min", refs, ajustados)
    lista += [
        Candidato("XGBoost sobre lo de ayer", lambda: Residual(fab.ml("xgboost", R, f), "prev_ciclo_inicio_min"),
                  "Aprende cuánto se corre respecto de ayer"),
        Candidato("Estructura del día (LightGBM)",
                  lambda: InicioEstructural(fab.ml("lightgbm", R, f), fab.ml("lightgbm", R, f)),
                  "Predice la hora del 1er ciclo y la separación de los siguientes"),
        Candidato("Estructura del día (XGBoost)",
                  lambda: InicioEstructural(fab.ml("xgboost", R, f), fab.ml("xgboost", R, f)),
                  "Predice la hora del 1er ciclo y la separación de los siguientes"),
        Candidato("XGBoost + reglas de horario", lambda: RestriccionHoraria(fab.ml("xgboost", R, f)),
                  "Evita horas que casi nunca se usan (<1 % de los ciclos)"),
        Candidato("LightGBM + reglas de horario", lambda: RestriccionHoraria(fab.ml("lightgbm", R, f)),
                  "Evita horas que casi nunca se usan (<1 % de los ciclos)"),
        Candidato("Franja del día (LightGBM)", lambda: FranjaClasificador(fab.ml("lightgbm", "clasificacion", f)),
                  "Solo predice madrugada / mañana / tarde / noche (centro de la franja)"),
        # Escenarios: usan información que NO existe a la medianoche
        Candidato("ESCENARIO: operador da la hora del 1er ciclo",
                  lambda: InicioEstructural(fab.ml("lightgbm", R, f), fab.ml("lightgbm", R, f), True),
                  "El operador indica a qué hora arranca el turno; el sistema completa el resto",
                  grupo="escenario"),
        Candidato("ESCENARIO: operador da la hora de arranque del módulo",
                  lambda: fab.ml("xgboost", R, [*f, "inicio_modulo_real"]),
                  "Se conoce a qué hora arranca el 1er turno del módulo ese día", grupo="escenario"),
    ]
    return lista


def registro_m3ha(d: Datos, ajustados) -> list[Candidato]:
    fab = Fabrica(d.config, d.categoricas)
    f = d.f_ciclo
    refs = {"ayer": "prev_ciclo_m3ha", "media7": "ciclo_m3ha_media7", "d7": "ciclo_m3ha_d7",
            "habitual": "ciclo_m3ha_mediana7"}
    lista = [Candidato("actual (LightGBM)", lambda: fab.ml("lightgbm", "regresion", f), "El modelo en uso")]
    lista += _comunes(fab, f, "riego_m3ha", refs, ajustados)
    return lista


def ajustar_hiper(d: Datos, target: str, log, n_iter: int) -> tuple[dict[str, dict], pd.DataFrame]:
    """Búsqueda de hiperparámetros de LightGBM / XGBoost / CatBoost en dev3–dev5 (error promedio)."""
    fab = Fabrica(d.config, d.categoricas)
    f = d.f_ciclo
    medir = medir_inicio if target == "inicio_min" else medir_m3ha
    elegidos, tablas = {}, []
    for familia in ("lightgbm", "xgboost", "catboost"):
        espacio = espacio_busqueda(familia, "regresion")
        mejor, tabla = buscar_hiper(
            f"{target}/{familia}", (lambda pa, fa=familia: fab.ml(fa, "regresion", f, **pa)), espacio,
            preparador(d, target), medir, "mae", False, n_iter, log)
        elegidos[familia] = {k: (v.item() if hasattr(v, "item") else v) for k, v in mejor.items()}
        tablas.append(tabla.assign(target=target, familia=familia))
    return elegidos, pd.concat(tablas, ignore_index=True)


def ejecutar(d: Datos, target: str, lista_periodos, log, ajustados=None):
    ajustados = ajustados or {}
    if target == "inicio_min":
        reg, medir = registro_inicio(d, ajustados), medir_inicio
    else:
        reg, medir = registro_m3ha(d, ajustados), medir_m3ha
    res, pred = correr(reg, preparador(d, target), medir, lista_periodos, log, target)
    return res, pred, reg
