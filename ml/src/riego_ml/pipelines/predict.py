from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from riego_ml.config.loader import load_config
from riego_ml.config.schema import ConfigError
from riego_ml.inference.predict import Predictor, save_predictions
from riego_ml.utils.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera predicciones de riego por turno con un modelo entrenado."
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Ruta al YAML de configuración. Por defecto ml/config/train.yaml.",
    )
    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="Nombre del modelo entrenado (random_forest, xgboost, svr, mlp).",
    )
    parser.add_argument(
        "--input",
        type=str,
        default=None,
        help="Archivo de entrada. Si se omite, se usa data.source.path del YAML.",
    )
    parser.add_argument(
        "--sheet",
        type=str,
        default=None,
        help="Hoja de Excel a leer (opcional).",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Ruta de salida .xlsx o .csv. Por defecto ml/reports/predicciones_<modelo>.xlsx.",
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

    if args.sheet is not None:
        config.data.source.sheet = args.sheet

    try:
        predictor = Predictor(config, args.model)
        frame = predictor.predict(args.input)
        output = (
            Path(args.output)
            if args.output
            else Path(config.reports_dir) / f"predicciones_{args.model}.xlsx"
        )
        saved = save_predictions(frame, output, args.model)
    except Exception as exc:  # noqa: BLE001
        logger.exception("La predicción falló: %s", exc)
        return 1

    logger.info("Predicciones guardadas en: %s", saved)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
