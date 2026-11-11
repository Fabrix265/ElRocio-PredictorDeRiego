"""Paso 3 - Entrena y compara RF / XGBoost / SVR / MLP y guarda el plan elegido.

Entrada: salidas del paso 2 en ``rutas.processed_dir``.
Salidas:

* ``ml/models/plan_riego/modelo_plan_riego.joblib``  modelo final (PlanRiego).
* ``ml/models/plan_riego/metadata.json``             elegidos, métricas y config.
* ``ml/reports/metricas_modelos.xlsx``               comparación, confusión,
  importancias, plan en test y fechas del split.

Uso::

    python ml/src/riego_ml/pipelines/entrenar.py
    python ml/src/riego_ml/pipelines/entrenar.py --modelos random_forest,xgboost --tuning
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from riego_ml.config import Config, load_config
from riego_ml.modeling.entrenamiento import entrenar
from riego_ml.utils.logging import configure_logging


def aplicar_opciones(config: Config, modelos: str | None, tuning: bool, n_iter: int | None) -> Config:
    if modelos:
        elegidos = {m.strip().lower() for m in modelos.split(",") if m.strip()}
        desconocidos = elegidos - set(config.modelos)
        if desconocidos:
            raise SystemExit(f"Modelos desconocidos: {sorted(desconocidos)}")
        for nombre, modelo in config.modelos.items():
            modelo.habilitado = nombre in elegidos
    if tuning:
        config.tuning.habilitado = True
    if n_iter:
        config.tuning.n_iter = n_iter
    return config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paso 3: entrena los modelos del plan de riego.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--modelos", default=None, help="Lista separada por comas (def. los habilitados en el YAML).")
    parser.add_argument("--tuning", action="store_true", help="Activa la búsqueda de hiperparámetros.")
    parser.add_argument("--n-iter", type=int, default=None, help="Combinaciones por modelo en el tuning.")
    args = parser.parse_args(argv)
    config = aplicar_opciones(load_config(args.config), args.modelos, args.tuning, args.n_iter)
    entrenar(config, configure_logging())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
