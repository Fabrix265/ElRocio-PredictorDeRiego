from __future__ import annotations

import logging
from pathlib import Path

from riego_ml.settings import LOGS_DIR


def configure_logging(
    name: str = "riego_ml",
    level: int = logging.INFO,
    log_file: str | Path | None = None,
) -> logging.Logger:
    """Logger con salida a consola y a ``ml/logs/riego_ml.log``."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.propagate = False
    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)

    log_path = Path(log_file) if log_file else LOGS_DIR / "riego_ml.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger
