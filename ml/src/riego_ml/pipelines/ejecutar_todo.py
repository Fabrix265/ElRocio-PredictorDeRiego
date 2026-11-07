"""Ejecuta el pipeline completo: (0) Phytech -> (1) unir -> (2) preparar -> (3) entrenar.

Uso::

    python ml/src/riego_ml/pipelines/ejecutar_todo.py                 # pasos 1-3
    python ml/src/riego_ml/pipelines/ejecutar_todo.py --con-phytech   # regenera también data_phytech.xlsx
    python ml/src/riego_ml/pipelines/ejecutar_todo.py --desde 2  # solo pasos 2-3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from riego_ml.config import load_config
from riego_ml.modeling.entrenamiento import entrenar
from riego_ml.pipelines import limpiar_phytech, preparar_dataset, unir_datos
from riego_ml.utils.logging import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pipeline completo del plan de riego.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--con-phytech", action="store_true", help="Ejecuta también el paso 0 (Phytech crudo).")
    parser.add_argument("--desde", type=int, default=1, choices=[1, 2, 3], help="Paso desde el que empezar.")
    args = parser.parse_args(argv)
    config = load_config(args.config)
    logger = configure_logging()

    if args.con_phytech:
        limpiar_phytech.main(["--salida", str(config.rutas.phytech)])
    if args.desde <= 1:
        unir_datos.ejecutar(config)
    if args.desde <= 2:
        preparar_dataset.ejecutar(config)
    entrenar(config, logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
