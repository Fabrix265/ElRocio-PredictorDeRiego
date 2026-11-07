"""Evalúa un modelo guardado (``PlanRiego``) sobre un período cualquiera.

Sirve para comparaciones justas: por ejemplo, medir el modelo anterior y el
nuevo exactamente sobre las mismas fechas y filas. Usa las tablas del paso 2
(``turno_dia.csv`` / ``ciclos.csv``), que traen las features calculadas solo
con información hasta el día anterior.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from riego_ml.dataset.limpieza import CLAVES_TD
from riego_ml.modeling import metricas
from riego_ml.modeling.planificador import PlanRiego


def _filtrar(df: pd.DataFrame, desde, hasta, excluir_incompletos: bool) -> pd.DataFrame:
    m = df["Fecha"] >= pd.Timestamp(desde)
    if hasta:
        m &= df["Fecha"] <= pd.Timestamp(hasta)
    if excluir_incompletos and "dia_incompleto" in df:
        m &= df["dia_incompleto"].fillna(0) == 0
    return df[m]


def evaluar_plan(
    plan: PlanRiego,
    turno_dia: pd.DataFrame,
    ciclos: pd.DataFrame,
    desde: str,
    hasta: str | None = None,
    excluir_incompletos: bool = True,
    nombre: str = "modelo",
) -> pd.DataFrame:
    """Métricas por target, con el mismo formato que ``comparacion_modelos.csv``."""
    maxc = plan.max_ciclos
    etiquetas = list(range(1, maxc + 1))
    td = _filtrar(turno_dia, desde, hasta, excluir_incompletos).reset_index(drop=True)
    ci = _filtrar(ciclos[ciclos["n_ciclos"] <= maxc], desde, hasta, excluir_incompletos).reset_index(drop=True)
    if td.empty or ci.empty:
        raise ValueError(f"No hay datos entre {desde} y {hasta or 'el final'}.")
    filas = []

    def registrar(target, valores):
        filas.append({"modelo": nombre, "target": target,
                      **{k: v for k, v in valores.items() if k != "confusion"}})

    real_n = td["n_ciclos"].clip(upper=maxc)
    registrar("n_ciclos", metricas.clasificacion(real_n, plan.predecir_n_ciclos(td), etiquetas))

    pred_m3ha = np.clip(plan.modelos["riego_m3ha"].predict(ci[plan.features["riego_m3ha"]]), *plan.rango_m3ha)
    registrar("riego_m3ha", metricas.regresion(ci["riego_m3ha"], pred_m3ha))
    pred_inicio = np.clip(plan.modelos["inicio_min"].predict(ci[plan.features["inicio_min"]]), 0, 1439)
    registrar("inicio_min", metricas.regresion(ci["inicio_min"], pred_inicio))
    duracion = plan.duracion(ci, pred_m3ha)
    registrar("duracion_min", metricas.regresion(ci["duracion_min"], duracion))
    registrar("fin_min", metricas.regresion(ci["fin_min"], pred_inicio + duracion))

    for target, modelo in plan.rangos.items():
        bajo, alto = modelo.predict(ci[modelo.columnas_])
        real = ci[target].to_numpy()
        filas.append({"modelo": nombre, "target": f"rango {target}", "n": len(real),
                      "cobertura": float(np.mean((real >= bajo) & (real <= alto))),
                      "ancho_medio": float(np.mean(alto - bajo))})

    predicho = plan.predecir(td, ciclos)
    resumen = predicho.groupby(CLAVES_TD).agg(
        riego_total_m3ha=("riego_m3ha", "sum"), duracion_total_min=("duracion_min", "sum"),
        inicio_primer_min=("inicio_min", "min"), fin_ultimo_min=("fin_min", "max"),
    ).reset_index()
    comparado = td.merge(resumen, on=CLAVES_TD, suffixes=("_real", "_pred"))
    for target in ("riego_total_m3ha", "duracion_total_min", "inicio_primer_min", "fin_ultimo_min"):
        registrar(f"plan: {target}", metricas.regresion(comparado[f"{target}_real"], comparado[f"{target}_pred"]))
    return pd.DataFrame(filas)


def tabla_comparativa(resultados: pd.DataFrame) -> pd.DataFrame:
    """Tabla ancha: una fila por métrica clave, una columna por modelo."""
    claves = [
        ("n_ciclos", "accuracy", "N° ciclos: acierto"),
        ("n_ciclos", "accuracy_pm1", "N° ciclos: acierto ±1"),
        ("n_ciclos", "f1_macro", "N° ciclos: F1 macro"),
        ("riego_m3ha", "rmse", "m3/ha: RMSE"),
        ("riego_m3ha", "mae", "m3/ha: MAE"),
        ("riego_m3ha", "r2", "m3/ha: R²"),
        ("inicio_min", "rmse", "Inicio: RMSE (min)"),
        ("inicio_min", "mae", "Inicio: MAE (min)"),
        ("inicio_min", "r2", "Inicio: R²"),
        ("duracion_min", "mae", "Duración: MAE (min)"),
        ("duracion_min", "mbe", "Duración: sesgo (min)"),
        ("plan: riego_total_m3ha", "rmse", "Plan: RMSE total m3/ha"),
        ("plan: riego_total_m3ha", "mae", "Plan: MAE total m3/ha"),
        ("plan: inicio_primer_min", "mae", "Plan: MAE inicio 1er ciclo (min)"),
        ("rango riego_m3ha", "cobertura", "Rango m3/ha: cobertura"),
        ("rango inicio_min", "cobertura", "Rango inicio: cobertura"),
    ]
    filas = []
    for target, metrica, etiqueta in claves:
        fila = {"Métrica": etiqueta}
        for modelo, g in resultados.groupby("modelo", sort=False):
            d = g[g["target"] == target]
            fila[modelo] = float(d[metrica].iloc[0]) if len(d) and metrica in d and pd.notna(d[metrica].iloc[0]) else np.nan
        filas.append(fila)
    return pd.DataFrame(filas)


TAREAS = {
    "n_ciclos": ("clasificacion", "n_ciclos_clase"),
    "riego_m3ha": ("regresion", "riego_m3ha"),
    "inicio_min": ("regresion", "inicio_min"),
}


def reentrenar_hasta(config, plan_ref: PlanRiego, turno_dia: pd.DataFrame, ciclos: pd.DataFrame,
                     columnas: dict, fecha: str, logger=None) -> PlanRiego:
    """Rearma ``plan_ref`` (mismos modelos y parámetros) usando solo datos hasta ``fecha``.

    Permite comparar modelos "como si se hubieran entrenado ese día" sobre un
    período que ninguno de los dos vio.
    """
    from riego_ml.modeling.entrenamiento import Entrenador

    corte = pd.Timestamp(fecha)
    maxc = plan_ref.max_ciclos
    td = turno_dia[turno_dia["Fecha"] <= corte].copy()
    td["n_ciclos_clase"] = td["n_ciclos"].clip(upper=maxc).astype(int)
    ci = ciclos[(ciclos["Fecha"] <= corte) & (ciclos["n_ciclos"] <= maxc)].copy()

    ent = Entrenador(config, logger)
    ent.categoricas = list(columnas["categoricas"])
    ent.f_turno = list(columnas["features_turno"])
    ent.f_ciclo = list(columnas["features_ciclo"])
    ent.etiquetas = list(range(1, maxc + 1))
    meta = plan_ref.metadata["elegidos"]
    ent.elegidos = {
        t: {"familia": meta[t]["familia"], "tarea": TAREAS[t][0], "target": TAREAS[t][1],
            "features": plan_ref.features[t], "params": meta[t]["params"]}
        for t in TAREAS
    }
    modelos = {}
    for t, info in ent.elegidos.items():
        datos = td if info["tarea"] == "clasificacion" else ci
        est = ent._crear(t, info["familia"], info["tarea"], info["features"], info["params"])
        modelos[t] = ent._ajustar(est, datos[info["features"]], datos[info["target"]])
    margenes = {t: getattr(m, "margen_", 0.0) for t, m in plan_ref.rangos.items()}
    rangos = ent._entrenar_rangos(ci, margenes) if plan_ref.rangos else {}
    return ent._plan(modelos, ci, rangos, metadata={
        "version": f"{plan_ref.metadata.get('version', 'actual')} reentrenado",
        "rango_datos": f"{td['Fecha'].min():%Y-%m-%d} a {td['Fecha'].max():%Y-%m-%d}",
        "elegidos": meta,
    })
