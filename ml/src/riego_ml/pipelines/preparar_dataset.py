"""Paso 2 - Limpia el dataset unido y deja las tablas listas para entrenar.

Entrada: salidas del paso 1 en ``rutas.interim_dir``.
Salidas en ``rutas.processed_dir`` (por defecto ``ml/data/processed``):

* ``turno_dia.csv``            1 fila por turno-día (target: n_ciclos).
* ``ciclos.csv``               1 fila por ciclo (targets: riego_m3ha, inicio_min).
* ``columnas.json``            listas de features y targets.
* ``dataset_entrenamiento.xlsx`` revisión: tablas, descartados y diagnóstico.

Uso::

    python ml/src/riego_ml/pipelines/preparar_dataset.py [--config ...] [--sin-excel]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from riego_ml.config import Config, load_config
from riego_ml.dataset.preparar import cargar_historial, guardar, preparar_entrenamiento
from riego_ml.utils.excel import dict_to_frame, write_excel
from riego_ml.utils.logging import configure_logging


def ejecutar(config: Config, excel: bool = True) -> dict:
    logger = configure_logging()
    logger.info("Paso 2 - Limpieza y preparación del dataset")
    historial = cargar_historial(config)
    dataset = preparar_entrenamiento(historial, config)
    salida = config.rutas.processed_dir
    guardar(dataset, salida)
    if excel:
        columnas = pd.DataFrame(
            [(k, ", ".join(v) if isinstance(v, list) else v) for k, v in dataset.columnas.items()],
            columns=["Grupo", "Columnas"],
        )
        write_excel(
            salida / "dataset_entrenamiento.xlsx",
            {
                "Turno_dia": dataset.turno_dia,
                "Ciclos": dataset.ciclos,
                "Descartados": historial.descartados,
                "Diagnostico": dict_to_frame(dataset.diagnostico),
                "Columnas": columnas,
            },
        )
    for clave, valor in dataset.diagnostico.items():
        logger.info("  %s: %s", clave, valor)
    logger.info("Salida: %s", salida)
    return dataset.diagnostico


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paso 2: limpia y prepara el dataset de entrenamiento.")
    parser.add_argument("--config", default=None)
    parser.add_argument("--sin-excel", action="store_true", help="No genera el Excel de revisión.")
    args = parser.parse_args(argv)
    ejecutar(load_config(args.config), excel=not args.sin_excel)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
