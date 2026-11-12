"""Corre todos los experimentos y arma el reporte comparativo.

Desde la raíz del repositorio::

    ml/.venv/Scripts/python ml/experimentos/ejecutar.py                # todo (~1-2 h)
    ml/.venv/Scripts/python ml/experimentos/ejecutar.py --rapido       # solo dev5 + final, sin ajuste
    ml/.venv/Scripts/python ml/experimentos/ejecutar.py --solo reporte # rehace el Excel con lo ya calculado

No toca ``ml/models``, ``config/pipeline.yaml`` ni el backend. Resultados en
``ml/reports/experimentos/<carpeta>/``.
"""

from __future__ import annotations

import argparse
import json
import time

import pandas as pd

import exp_ciclo
import exp_n_ciclos
import exp_plan
import exp_rangos
import reporte
from comun import Candidato, carpeta_resultados, cargar_datos, logger, periodos, resumir

PASOS = ("n_ciclos", "ajuste", "inicio_min", "riego_m3ha", "rangos", "plan", "reporte")


def _leer(carpeta, nombre):
    ruta = carpeta / "datos" / f"{nombre}.csv"
    return pd.read_csv(ruta) if ruta.exists() else None


def _ganador(tabla: pd.DataFrame, clave: str, mayor_mejor: bool, actual: str) -> str:
    """El mejor en desarrollo entre los que compiten; si no supera al actual, queda el actual.

    En regresión además se exige no empeorar más de 5 % el RMSE del actual en desarrollo:
    un modelo con buen error promedio pero fallos grandes (p. ej. copiar ayer) no sirve.
    """
    t = tabla[tabla["grupo"] == "modelo"].dropna(subset=[f"{clave}_dev"])
    if "rmse_dev" in t:
        t = t[t["rmse_dev"] <= 1.05 * t.loc[actual, "rmse_dev"]]
    mejor = t[f"{clave}_dev"].idxmax() if mayor_mejor else t[f"{clave}_dev"].idxmin()
    ref = t.loc[actual, f"{clave}_dev"]
    gana = t.loc[mejor, f"{clave}_dev"] > ref if mayor_mejor else t.loc[mejor, f"{clave}_dev"] < ref
    return mejor if gana else actual


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo", nargs="*", choices=PASOS, default=list(PASOS))
    ap.add_argument("--rapido", action="store_true", help="solo dev5 + final y sin ajuste de hiperparámetros")
    ap.add_argument("--n-iter", type=int, default=12, help="combinaciones por modelo en el ajuste")
    ap.add_argument("--carpeta", default="ultimo")
    args = ap.parse_args()

    log = logger()
    t0 = time.time()
    carpeta = carpeta_resultados(args.carpeta)
    datos_dir = carpeta / "datos"
    lista = periodos(solo=["dev5", "final"]) if args.rapido else periodos()
    d = cargar_datos()
    log.info("Datos: %d turno-días, %d ciclos. Períodos: %s", len(d.turno_dia), len(d.ciclos),
             [p.nombre for p in lista])

    ruta_ajuste = datos_dir / "hiperparametros.json"
    ajustados = json.loads(ruta_ajuste.read_text(encoding="utf-8")) if ruta_ajuste.exists() else {}

    if "n_ciclos" in args.solo:
        log.info("== A. N° de ciclos ==")
        res, pred, _ = exp_n_ciclos.ejecutar(d, lista, log)
        res.to_csv(datos_dir / "n_ciclos.csv", index=False)
        pd.DataFrame(pred).to_csv(datos_dir / "pred_final_n_ciclos.csv", index=False)

    if "ajuste" in args.solo and not args.rapido:
        log.info("== Ajuste de hiperparámetros (dev3–dev5) ==")
        tablas = []
        for target in ("riego_m3ha", "inicio_min"):
            elegidos, tabla = exp_ciclo.ajustar_hiper(d, target, log, args.n_iter)
            ajustados[target] = elegidos
            tablas.append(tabla)
        ruta_ajuste.write_text(json.dumps(ajustados, indent=2, ensure_ascii=False), encoding="utf-8")
        pd.concat(tablas, ignore_index=True).to_csv(datos_dir / "ajuste_hiper.csv", index=False)

    for target in ("inicio_min", "riego_m3ha"):
        if target in args.solo:
            log.info("== %s ==", target)
            res, pred, _ = exp_ciclo.ejecutar(d, target, lista, log, ajustados.get(target, {}))
            res.to_csv(datos_dir / f"{target}.csv", index=False)
            pd.DataFrame(pred).to_csv(datos_dir / f"pred_final_{target}.csv", index=False)

    # Ganadores (por promedio en desarrollo)
    reg = {
        "n_ciclos": {c.nombre: c for c in exp_n_ciclos.registro(d)},
        "inicio_min": {c.nombre: c for c in exp_ciclo.registro_inicio(d, ajustados.get("inicio_min", {}))},
        "riego_m3ha": {c.nombre: c for c in exp_ciclo.registro_m3ha(d, ajustados.get("riego_m3ha", {}))},
    }
    actuales = {"n_ciclos": "actual (repetir ayer salvo cambio seguro LGBM)", "inicio_min": "actual (XGBoost)",
                "riego_m3ha": "actual (LightGBM)"}
    claves = {"n_ciclos": ("accuracy", True, exp_n_ciclos.METRICAS),
              "inicio_min": ("mae", False, exp_ciclo.METRICAS_INICIO),
              "riego_m3ha": ("mae", False, exp_ciclo.METRICAS_M3HA)}
    tablas, ganadores = {}, {}
    for target, (clave, mayor, cols) in claves.items():
        res = _leer(carpeta, target)
        if res is None:
            continue
        tablas[target] = resumir(res, [c for c in cols if c in res], clave, mayor, actuales[target])
        ganadores[target] = _ganador(tablas[target], clave, mayor, actuales[target])
    log.info("Ganadores en desarrollo: %s", ganadores)

    if "rangos" in args.solo:
        log.info("== Rangos ==")
        puntos = {t: reg[t][ganadores.get(t, actuales[t])].crear for t in ("riego_m3ha", "inicio_min")}
        exp_rangos.ejecutar(d, lista, log, puntos).to_csv(datos_dir / "rangos.csv", index=False)

    if "plan" in args.solo and len(ganadores) == 3:
        log.info("== Plan completo ==")
        actual = {t: reg[t][actuales[t]] for t in actuales}
        mejor = {t: reg[t][ganadores[t]] for t in actuales}
        combinaciones: dict[str, dict[str, Candidato]] = {"actual": actual, "mejor combinación": mejor}
        for t, nombre in (("n_ciclos", "n° de ciclos"), ("riego_m3ha", "m3/ha"), ("inicio_min", "hora de inicio")):
            if ganadores[t] != actuales[t]:
                combinaciones[f"actual + mejor {nombre}"] = {**actual, t: mejor[t]}
        exp_plan.ejecutar(d, combinaciones, lista, log).to_csv(datos_dir / "plan.csv", index=False)

    if "reporte" in args.solo:
        reporte.generar(carpeta, tablas, ganadores, actuales, reg, ajustados, log)
    log.info("Listo en %.1f min. Resultados: %s", (time.time() - t0) / 60, carpeta)


if __name__ == "__main__":
    main()
