"""Paso 0 - Limpia las descargas crudas de Phytech y genera ``data_phytech.xlsx``.

Uso (desde la raíz del repositorio)::

    python ml/src/riego_ml/pipelines/limpiar_phytech.py
    python ml/src/riego_ml/pipelines/limpiar_phytech.py --area-id 12537 --plot-id 70208
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd

from riego_ml.settings import DATA_RAW_DIR
from riego_ml.sources.phytech_crudo import LEYENDA, limpiar_phytech
from riego_ml.utils.excel import dict_to_frame, write_excel
from riego_ml.utils.logging import configure_logging

CARPETA_DEFAULT = DATA_RAW_DIR / "phytech" / "completo"
AREA_ID_DEFAULT = 12537   # área Phytech "ENSUEÑO 2" (contiene el plot ENSUEÑO 1)
PLOT_ID_DEFAULT = 70208   # plot Phytech "ENSUEÑO 1"
FUNDO_DEFAULT = "ENSUEÑO 1"
SALIDA_DEFAULT = DATA_RAW_DIR / "data_phytech.xlsx"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Limpia los datos crudos de Phytech de un plot.")
    parser.add_argument("--carpeta", type=Path, default=CARPETA_DEFAULT)
    parser.add_argument("--area-id", type=int, default=AREA_ID_DEFAULT)
    parser.add_argument("--plot-id", type=int, default=PLOT_ID_DEFAULT)
    parser.add_argument("--fundo", default=FUNDO_DEFAULT)
    parser.add_argument("--salida", type=Path, default=SALIDA_DEFAULT)
    args = parser.parse_args(argv)
    logger = configure_logging()

    logger.info("Limpiando Phytech: %s (area %s, plot %s)", args.carpeta, args.area_id, args.plot_id)
    limpio = limpiar_phytech(args.carpeta, args.area_id, args.plot_id, args.fundo)
    write_excel(
        args.salida,
        {
            "Suelo_horario": limpio.suelo_horario,
            "Suelo_diario": limpio.suelo_diario,
            "Planta_diario": limpio.planta_diario,
            "Leyenda": pd.DataFrame(LEYENDA, columns=["Columna", "Unidad", "Descripcion"]),
            "Diagnostico": dict_to_frame(limpio.diagnostico),
        },
    )
    for clave, valor in limpio.diagnostico.items():
        logger.info("  %s: %s", clave, valor)
    logger.info("Salida: %s", args.salida)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
