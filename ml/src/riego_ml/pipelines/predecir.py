"""Paso 4 - Predice el plan de riego de una o varias fechas.

Por cada turno y fecha devuelve: número de ciclos y, por ciclo, m3/ha, m3,
duración (min), hora de inicio y hora de fin.

Uso::

    python ml/src/riego_ml/pipelines/predecir.py                      # día siguiente al último registro
    python ml/src/riego_ml/pipelines/predecir.py --fecha 2025-04-25
    python ml/src/riego_ml/pipelines/predecir.py --fecha 2025-04-25 --dias 3 --salida plan.xlsx

Usa el historial del paso 1 (``rutas.interim_dir``) para calcular las features
del día anterior, por lo que conviene volver a correr ``unir_datos.py`` cuando
lleguen datos nuevos.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from riego_ml.config import load_config
from riego_ml.dataset.preparar import cargar_historial
from riego_ml.modeling.planificador import plan_ancho
from riego_ml.modeling.prediccion import cargar_plan, planificar
from riego_ml.utils.excel import write_excel
from riego_ml.utils.logging import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paso 4: predice el plan de riego.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--fecha", default=None, help="YYYY-MM-DD (def. día siguiente al último riego registrado).")
    parser.add_argument("--dias", type=int, default=1, help="Cantidad de días consecutivos a planificar.")
    parser.add_argument("--modelo", default=None, help="Ruta a un modelo_plan_riego.joblib alternativo.")
    parser.add_argument("--salida", default=None, help="Archivo .xlsx o .csv (def. ml/reports/plan_riego_<fecha>.xlsx).")
    args = parser.parse_args(argv)
    logger = configure_logging()

    config = load_config(args.config)
    plan = cargar_plan(config, args.modelo)
    historial = cargar_historial(config)
    inicio = pd.Timestamp(args.fecha) if args.fecha else historial.ciclos["Fecha"].max() + pd.Timedelta(days=1)
    fechas = list(pd.date_range(inicio, periods=max(1, args.dias), freq="D"))
    logger.info("Planificando %s a %s con %s", f"{fechas[0]:%Y-%m-%d}", f"{fechas[-1]:%Y-%m-%d}", plan.elegidos)

    resultado = planificar(plan, historial, fechas, config)
    ancho = plan_ancho(resultado, plan.max_ciclos)
    salida = Path(args.salida) if args.salida else config.rutas.reportes_dir / f"plan_riego_{fechas[0]:%Y-%m-%d}.xlsx"
    if salida.suffix.lower() == ".csv":
        salida.parent.mkdir(parents=True, exist_ok=True)
        resultado.to_csv(salida, index=False)
    else:
        write_excel(salida, {"Plan_por_turno": ancho, "Plan_por_ciclo": resultado})

    columnas = ["Fecha", "Turno", "n_ciclos", "Ciclo", "riego_m3ha", "duracion_min", "hora_inicio", "hora_fin"]
    print(resultado[columnas].to_string(index=False))
    logger.info("Plan guardado en %s", salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
