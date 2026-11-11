"""Paso 1 - Une riego (base) + meteorología + Phytech.

Salidas en ``rutas.interim_dir`` (por defecto ``ml/data/interim``):

* ``riego_unido.csv``     1 fila por ciclo de riego con el ambiente del día.
* ``ambiente_diario.csv`` calendario diario continuo de meteo + Phytech.
* ``dataset_unido.xlsx``  las dos tablas + diagnóstico + diccionario (revisión).

Uso::

    python ml/src/riego_ml/pipelines/unir_datos.py [--config ml/config/pipeline.yaml]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from riego_ml.config import Config, load_config
from riego_ml.dataset.unir import DICCIONARIO, unir_fuentes
from riego_ml.utils.excel import dict_to_frame, write_excel
from riego_ml.utils.logging import configure_logging


def ejecutar(config: Config) -> dict:
    logger = configure_logging()
    rutas = config.rutas
    logger.info("Paso 1 - Uniendo fuentes (base: %s)", rutas.riego.name)
    resultado = unir_fuentes(
        rutas.riego,
        rutas.meteo,
        rutas.phytech,
        hoja_riego=config.fuentes.hoja_riego,
        phytech_project_id=config.fuentes.phytech_project_id,
        carpeta_phytech_crudo=rutas.phytech_crudo,
        phytech_area_id=config.fuentes.phytech_area_id,
        phytech_plot_id=config.fuentes.phytech_plot_id,
    )
    salida = rutas.interim_dir
    salida.mkdir(parents=True, exist_ok=True)
    resultado.riego_unido.to_csv(salida / "riego_unido.csv", index=False)
    resultado.ambiente_diario.to_csv(salida / "ambiente_diario.csv", index=False)
    write_excel(
        salida / "dataset_unido.xlsx",
        {
            "Riego_unido": resultado.riego_unido,
            "Ambiente_diario": resultado.ambiente_diario,
            "Diagnostico": dict_to_frame(resultado.diagnostico),
            "Diccionario": pd.DataFrame(DICCIONARIO.items(), columns=["Columna", "Descripcion"]),
        },
    )
    for clave, valor in resultado.diagnostico.items():
        logger.info("  %s: %s", clave, valor)
    logger.info("Salida: %s", salida)
    return resultado.diagnostico


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paso 1: une riego + meteo + Phytech.")
    parser.add_argument("--config", default=None, help="Ruta al YAML (def. ml/config/pipeline.yaml).")
    args = parser.parse_args(argv)
    ejecutar(load_config(args.config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
