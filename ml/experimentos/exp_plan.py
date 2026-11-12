"""Experimento D2: el plan completo del día (n° de ciclos predicho -> ciclos -> horario).

Usa ``PlanRiego`` de ``riego_ml`` tal cual (mismo armado del horario que el modelo
en uso), cambiando solo las piezas.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from comun import MAX_CICLOS, Candidato, Datos, Periodo, ajustar, mascara_eval, metricas_reg
from riego_ml.dataset.limpieza import CLAVES_TD
from riego_ml.modeling.planificador import PlanRiego

TOTALES = ["riego_total_m3ha", "duracion_total_min", "inicio_primer_min", "fin_ultimo_min"]


def _plan(d: Datos, modelos: dict, ci_train: pd.DataFrame) -> PlanRiego:
    extra = ["Fecha", "Fundo", "Modulo"]
    return PlanRiego(
        modelos=modelos,
        features={"n_ciclos": [*d.f_turno, "Fecha"], "riego_m3ha": [*d.f_ciclo, *extra],
                  "inicio_min": [*d.f_ciclo, *extra]},
        max_ciclos=MAX_CICLOS,
        min_por_m3ha=(ci_train["duracion_min"] / ci_train["riego_m3ha"]).groupby(ci_train["Turno"]).median()
        .round(4).to_dict(),
        area_ha=ci_train.groupby("Turno")["area_ha"].median().round(4).to_dict(),
        rango_m3ha=(float(ci_train["riego_m3ha"].quantile(0.001)), float(ci_train["riego_m3ha"].quantile(0.999))),
        pausa_min=0,
        caudal_dinamico=True,
    )


def ejecutar(d: Datos, combinaciones: dict[str, dict[str, Candidato]], lista_periodos: list[Periodo],
             log) -> pd.DataFrame:
    td, ci = d.turno_dia, d.ciclos
    filas = []
    for p in lista_periodos:
        tr_td, ev_td = p.mascaras(td["Fecha"])
        ev_td &= mascara_eval(td)
        tr_ci, _ = p.mascaras(ci["Fecha"])
        cache: dict[tuple[str, str], object] = {}
        for nombre, piezas in combinaciones.items():
            t0 = time.time()
            modelos = {}
            for target, cand in piezas.items():
                if (target, cand.nombre) not in cache:
                    datos, y = (td[tr_td], td.loc[tr_td, "n_ciclos_clase"]) if target == "n_ciclos" else (
                        ci[tr_ci], ci.loc[tr_ci, target])
                    cache[(target, cand.nombre)] = ajustar(cand.crear(), datos, y)
                modelos[target] = cand.aplicar(cache[(target, cand.nombre)])
            plan = _plan(d, modelos, ci[tr_ci])
            evaluar = td[ev_td]
            predicho = plan.predecir(evaluar, d.ciclos_hist)
            resumen = predicho.groupby(CLAVES_TD).agg(
                n_ciclos_pred=("n_ciclos", "first"), riego_total_m3ha=("riego_m3ha", "sum"),
                duracion_total_min=("duracion_min", "sum"), inicio_primer_min=("inicio_min", "min"),
                fin_ultimo_min=("fin_min", "max")).reset_index()
            comp = evaluar.merge(resumen, on=CLAVES_TD, suffixes=("_real", "_pred"))
            fila = {"combinacion": nombre, "periodo": p.nombre, "n": len(comp),
                    "acierto_n_ciclos": float(np.mean(comp["n_ciclos_clase"] == comp["n_ciclos_pred"]))}
            for t in TOTALES:
                m = metricas_reg(comp[f"{t}_real"], comp[f"{t}_pred"])
                fila.update({f"{t}_mae": m["mae"], f"{t}_rmse": m["rmse"], f"{t}_mbe": m["mbe"]})
            filas.append(fila)
            log.info("  plan %-6s %-45s acierto=%.3f agua MAE=%.2f inicio MAE=%.0f (%.0fs)", p.nombre, nombre,
                     fila["acierto_n_ciclos"], fila["riego_total_m3ha_mae"], fila["inicio_primer_min_mae"],
                     time.time() - t0)
    return pd.DataFrame(filas)
