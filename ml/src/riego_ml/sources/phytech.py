"""Lectura del Phytech ya limpio (``data_phytech.xlsx``) y resumen diario.

Se usa un sensor (``project_id``) del plot: por defecto el 907557, que es el que
tiene historia desde 2022 y está conectado a la válvula Phytech del módulo.
Para cada día se obtiene:

* Humedad media del día por profundidad.
* Humedad "al cierre del día" (media de las 21-23 h): es la última foto del
  suelo disponible antes de planificar el riego del día siguiente.
* Datos de planta (MDS, crecimiento de tronco, índice de estrés).

:func:`leer_phytech` solo lee el Excel; :func:`resumir_phytech` arma el resumen
diario desde DataFrames con el formato de las hojas (también desde la BD).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from riego_ml.sources.phytech_crudo import HUM_COLS
from riego_ml.utils.tiempo import norm_text

PROJECT_ID_DEFAULT = 907557
HORAS_CIERRE = (21, 22, 23)

SUELO_VARS = [*HUM_COLS, "hum_zona_radicular", "hum_linea_estres"]
PLANTA_VARS = ["mds_contraccion_um", "crecimiento_tronco_um", "estres_planta_ps"]


RANGO_VARS = ["hum_45cm", "hum_60cm"]


def columnas_suelo_diario() -> list[str]:
    return [
        *[f"{c}_media" for c in SUELO_VARS],
        *[f"{c}_cierre" for c in SUELO_VARS],
        *[f"{c}_rango" for c in RANGO_VARS],
        "suelo_horas",
    ]


def leer_phytech(path: str | Path, project_id: int = PROJECT_ID_DEFAULT) -> tuple[pd.DataFrame, dict]:
    """Devuelve 1 fila por Fundo y día con suelo y planta del sensor elegido.

    Solo lee las hojas ``Suelo_horario`` y ``Planta_diario``; el resumen diario es
    :func:`resumir_phytech`, que también se aplica a las tablas guardadas en la BD.
    """
    horario = pd.read_excel(path, sheet_name="Suelo_horario")
    if not (horario["project_id"] == project_id).any():
        raise ValueError(f"El sensor {project_id} no está en {path} (hoja Suelo_horario).")
    planta = pd.read_excel(path, sheet_name="Planta_diario")
    diario = resumir_phytech(horario, planta, project_id)
    diag = {
        "Phytech: sensor usado": project_id,
        "Phytech: días con suelo": int(diario["suelo_horas"].notna().sum()),
        "Phytech: días con MDS": int(diario["mds_contraccion_um"].notna().sum()),
        "Phytech: rango de fechas": f"{diario['Fecha'].min():%Y-%m-%d} a {diario['Fecha'].max():%Y-%m-%d}",
    }
    return diario, diag


def resumir_phytech(
    horario: pd.DataFrame, planta: pd.DataFrame, project_id: int = PROJECT_ID_DEFAULT
) -> pd.DataFrame:
    """Resumen diario de suelo (horas con dato) y planta del sensor ``project_id``.

    ``horario`` tiene el formato de ``Suelo_horario`` (``fundo``, ``project_id``, ``fecha_hora``,
    ``hay_dato_phytech`` y las columnas de humedad) y ``planta`` el de ``Planta_diario``
    (``fundo``, ``project_id``, ``fecha`` y ``PLANTA_VARS``).
    """
    horario = horario[horario["project_id"] == project_id].copy()
    horario["Fundo"] = norm_text(horario["fundo"])
    horario["fecha_hora"] = pd.to_datetime(horario["fecha_hora"], errors="coerce")
    horario = horario.dropna(subset=["fecha_hora"])
    horario = horario[horario["hay_dato_phytech"] == 1]
    horario["Fecha"] = horario["fecha_hora"].dt.normalize()
    horario["hora"] = horario["fecha_hora"].dt.hour

    claves = ["Fundo", "Fecha"]
    media = horario.groupby(claves)[SUELO_VARS].mean().add_suffix("_media")
    cierre = (
        horario[horario["hora"].isin(HORAS_CIERRE)]
        .groupby(claves)[SUELO_VARS]
        .mean()
        .add_suffix("_cierre")
    )
    # Rango diario (máx - mín): cuánto respondió el suelo al riego del día. Es
    # relativo, por lo que no le afectan las recalibraciones del sensor.
    grupos = horario.groupby(claves)[RANGO_VARS]
    rango = (grupos.max() - grupos.min()).add_suffix("_rango")
    horas = horario.groupby(claves).size().rename("suelo_horas")
    suelo = pd.concat([media, cierre, rango, horas], axis=1).reset_index()

    planta = planta[planta["project_id"] == project_id].copy()
    planta["Fundo"] = norm_text(planta["fundo"])
    planta["Fecha"] = pd.to_datetime(planta["fecha"], errors="coerce").dt.normalize()
    planta = planta.dropna(subset=["Fecha"]).drop_duplicates(claves, keep="last")
    planta = planta[[*claves, *PLANTA_VARS]]

    diario = suelo.merge(planta, on=claves, how="outer").sort_values(claves)
    numericas = diario.select_dtypes("number").columns
    diario[numericas] = diario[numericas].round(3)
    diario = diario.reset_index(drop=True)
    return diario[[*claves, *columnas_suelo_diario(), *PLANTA_VARS]]
