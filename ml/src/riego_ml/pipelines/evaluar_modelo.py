"""Evalúa uno o varios modelos guardados sobre el mismo período (comparación justa).

Uso::

    # modelo actual vs una versión anterior, sobre el mismo período
    python ml/src/riego_ml/pipelines/evaluar_modelo.py --desde 2025-12-01 \\
        --modelos ml/models/plan_riego/actual ml/models/plan_riego/versiones/2026-11-07_0841

Salida: ``ml/reports/evaluaciones/evaluacion_<desde>_<hasta>.xlsx`` con la
tabla comparativa y el detalle por target.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from riego_ml.config import load_config
from riego_ml.dataset.preparar import cargar_dataset
from riego_ml.modeling.evaluacion import evaluar_plan, tabla_comparativa
from riego_ml.modeling.prediccion import cargar_plan
from riego_ml.utils.excel import write_excel
from riego_ml.utils.logging import configure_logging


def _nombre(ruta: Path, plan) -> str:
    version = plan.metadata.get("version") or (ruta.parent.name if ruta.suffix else ruta.name)
    return f"{version} (datos {plan.metadata.get('rango_datos', '?')})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evalúa modelos guardados sobre un mismo período.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--modelos", nargs="+", default=None,
                        help="Carpetas o archivos .joblib (def. el modelo actual).")
    parser.add_argument("--desde", required=True, help="YYYY-MM-DD")
    parser.add_argument("--hasta", default=None, help="YYYY-MM-DD (def. hasta el final de los datos)")
    parser.add_argument("--incluir-dias-incompletos", action="store_true")
    parser.add_argument("--salida", default=None)
    args = parser.parse_args(argv)
    logger = configure_logging()

    config = load_config(args.config)
    ds = cargar_dataset(config.rutas.processed_dir)
    rutas = [Path(m) for m in args.modelos] if args.modelos else [None]
    resultados = []
    for ruta in rutas:
        plan = cargar_plan(config, ruta)
        nombre = _nombre(ruta or Path("actual"), plan)
        logger.info("Evaluando %s entre %s y %s", nombre, args.desde, args.hasta or "el final")
        resultados.append(evaluar_plan(plan, ds.turno_dia, ds.ciclos, args.desde, args.hasta,
                                       not args.incluir_dias_incompletos, nombre))
    detalle = pd.concat(resultados, ignore_index=True)
    tabla = tabla_comparativa(detalle)
    salida = Path(args.salida) if args.salida else (
        config.rutas.reportes_dir / "evaluaciones" / f"evaluacion_{args.desde}_{args.hasta or 'fin'}.xlsx")
    write_excel(salida, {"Comparativa": tabla.round(4), "Detalle": detalle.round(4)})
    print(tabla.round(3).to_string(index=False))
    logger.info("Evaluación guardada en %s", salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
