"""Experimento D1: rangos probables (p10–p90) de m3/ha y hora de inicio.

Candidatos
----------
* ``actual``: dos LightGBM por cuantiles + un margen calibrado UNA vez con los
  últimos ~10 meses antes del período (la receta del pipeline en uso).
* ``cuantiles + margen móvil N días``: el mismo modelo, pero el margen se
  recalcula cada día con los errores de los últimos N días ya observados. En
  producción es posible: cada mañana ya se conoce el riego real hasta ayer.
* ``alrededor del valor predicho + margen móvil``: rango = predicción ± el error
  que se cometió el 80 % de las veces en los últimos 60 días.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd

from candidatos import Fabrica, margen_conformal, margen_movil
from comun import Datos, Periodo, ajustar, mascara_eval, metricas_rango

NIVEL = 0.80
DIAS_CAL = 300


def _cortes(ci: pd.DataFrame, p: Periodo):
    fin = p.fin if p.fin is not None else ci["Fecha"].max()
    tr = ci["Fecha"] <= p.fin_train
    cal = tr & (ci["Fecha"] > p.fin_train - pd.Timedelta(days=DIAS_CAL))
    sub = ci["Fecha"] <= p.fin_train - pd.Timedelta(days=DIAS_CAL + 7)
    post = (ci["Fecha"] > p.fin_train) & (ci["Fecha"] <= fin)   # días ya observados al predecir (gap + período)
    ev = (ci["Fecha"] >= p.inicio) & (ci["Fecha"] <= fin) & mascara_eval(ci)
    return tr, cal, sub, post, ev


def ejecutar(d: Datos, lista_periodos: list[Periodo], log, puntos: dict) -> pd.DataFrame:
    """``puntos``: target -> función que crea el modelo puntual (el elegido o el actual)."""
    fab = Fabrica(d.config, d.categoricas)
    f = d.f_ciclo
    ci = d.ciclos
    filas = []
    for target in ("riego_m3ha", "inicio_min"):
        for p in lista_periodos:
            t0 = time.time()
            tr, cal, sub, post, ev = _cortes(ci, p)
            y = ci[target].to_numpy(float)
            # Receta actual: calibrar con los últimos 10 meses, reentrenar con todo el train
            r_sub = ajustar(fab.rango(f), ci[sub], ci.loc[sub, target])
            margen_fijo = r_sub.calcular_margen(ci[cal], ci.loc[cal, target])
            r = ajustar(fab.rango(f), ci[tr], ci.loc[tr, target])
            bajo_ev, alto_ev = r._crudo(ci[ev])
            filas.append(dict(target=target, periodo=p.nombre, candidato="actual (cuantiles + margen fijo)",
                              **metricas_rango(y[ev], bajo_ev - margen_fijo, alto_ev + margen_fijo)))
            filas.append(dict(target=target, periodo=p.nombre, candidato="cuantiles sin margen",
                              **metricas_rango(y[ev], bajo_ev, alto_ev)))
            bajo_po, alto_po = r._crudo(ci[post])
            puntaje = np.maximum(bajo_po - y[post], y[post] - alto_po)
            for dias in (30, 60, 90):
                m = margen_movil(ci.loc[post, "Fecha"], puntaje, ci.loc[ev, "Fecha"], dias, NIVEL, margen_fijo)
                filas.append(dict(target=target, periodo=p.nombre, candidato=f"cuantiles + margen móvil {dias} días",
                                  **metricas_rango(y[ev], bajo_ev - m, alto_ev + m)))
            # Alrededor del valor predicho por el modelo puntual
            crear = puntos[target]
            m_sub = ajustar(crear(), ci[sub], ci.loc[sub, target])
            respaldo = margen_conformal(np.abs(m_sub.predict(ci[cal]) - y[cal]), NIVEL)
            modelo = ajustar(crear(), ci[tr], ci.loc[tr, target])
            pred_post = modelo.predict(ci[post])
            pred_ev = modelo.predict(ci[ev])
            for dias in (60,):
                m = margen_movil(ci.loc[post, "Fecha"], np.abs(pred_post - y[post]), ci.loc[ev, "Fecha"], dias,
                                 NIVEL, respaldo)
                filas.append(dict(target=target, periodo=p.nombre,
                                  candidato=f"valor predicho ± margen móvil {dias} días",
                                  **metricas_rango(y[ev], pred_ev - m, pred_ev + m)))
            filas.append(dict(target=target, periodo=p.nombre, candidato="valor predicho ± margen fijo",
                              **metricas_rango(y[ev], pred_ev - respaldo, pred_ev + respaldo)))
            log.info("  rango %-10s %-6s listo (%.0fs)", target, p.nombre, time.time() - t0)
    res = pd.DataFrame(filas)
    res["grupo"] = "modelo"
    return res


def resumir(res: pd.DataFrame) -> pd.DataFrame:
    dev = res[res["periodo"].str.startswith("dev")]
    fin = res[res["periodo"] == "final"]
    a = dev.groupby(["target", "candidato"])[["cobertura", "ancho_medio"]].agg(["mean", "min"])
    a.columns = ["cobertura_dev", "cobertura_dev_min", "ancho_dev", "_"]
    a = a.drop(columns="_")
    b = fin.set_index(["target", "candidato"])[["cobertura", "ancho_medio"]].rename(
        columns={"cobertura": "cobertura_final", "ancho_medio": "ancho_final"})
    return a.join(b).reset_index()


def elegir(tabla: pd.DataFrame) -> dict[str, str]:
    """Por target: el más angosto entre los que cubren 78–86 % en desarrollo; si ninguno, el más cercano a 80 %."""
    out = {}
    for target, g in tabla.groupby("target"):
        ok = g[(g["cobertura_dev"] >= 0.78) & (g["cobertura_dev"] <= 0.86)]
        if len(ok):
            out[target] = ok.sort_values("ancho_dev").iloc[0]["candidato"]
        else:
            out[target] = g.iloc[(g["cobertura_dev"] - NIVEL).abs().argsort()].iloc[0]["candidato"]
    return out
