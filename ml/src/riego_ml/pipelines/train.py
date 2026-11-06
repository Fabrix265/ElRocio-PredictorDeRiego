from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from riego_ml.config.loader import load_config
from riego_ml.config.schema import ConfigError
from riego_ml.training.trainer import Trainer
from riego_ml.utils.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Entrena los modelos de predicción de riego por turno."
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Ruta al YAML de entrenamiento. Por defecto ml/config/train.yaml.",
    )
    parser.add_argument("--seed", type=int, default=None, help="Semilla aleatoria.")
    parser.add_argument(
        "--test-size", type=float, default=None, help="Fracción de test (0-1)."
    )
    parser.add_argument(
        "--validation-size",
        type=float,
        default=None,
        help="Fracción de validación (0-1).",
    )
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="Lista separada por comas de modelos a entrenar (ej: random_forest,xgboost).",
    )
    parser.add_argument(
        "--name", type=str, default=None, help="Nombre de la corrida."
    )
    parser.add_argument(
        "--tune",
        action="store_true",
        help="Activa la búsqueda de hiperparámetros (RandomizedSearchCV).",
    )
    parser.add_argument(
        "--tune-iter",
        type=int,
        default=None,
        help="Número de combinaciones a probar por modelo cuando --tune está activo.",
    )
    parser.add_argument(
        "--tune-target",
        type=str,
        default=None,
        choices=["n_ciclos", "ciclo", "riego_m3ha", "both"],
        help="Target o etapa sobre la que se hace tuning.",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logger = configure_logging(level=getattr(logging, args.log_level))

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        logger.error("Configuración inválida: %s", exc)
        return 2

    if args.seed is not None:
        config.seed = args.seed
        config.split.random_state = args.seed
    if args.test_size is not None:
        config.split.test_size = args.test_size
    if args.validation_size is not None:
        config.split.validation_size = args.validation_size
    if args.name is not None:
        config.name = args.name
    if args.tune:
        config.tuning.enabled = True
    if args.tune_iter is not None:
        config.tuning.n_iter = max(1, args.tune_iter)
    if args.tune_target is not None:
        config.tuning.target = args.tune_target
    if args.models:
        selected = {
            name.strip().lower() for name in args.models.split(",") if name.strip()
        }
        for name, model_config in config.models.items():
            model_config.enabled = name.lower() in selected

    try:
        trainer = Trainer(config, logger=logger)
        summary = trainer.run()
    except Exception as exc:  # noqa: BLE001
        logger.exception("El entrenamiento falló: %s", exc)
        return 1

    logger.info("Resumen: %s", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
