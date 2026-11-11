"""Guardar lecturas limpias (formato de riego_ml) en las tablas de datos de campo.

Lo usan la carga histórica (``excel_historico``) y la ingesta de las APIs, para que ambas escriban
igual. Las tablas guardan la salida **saneada** de riego_ml:

- ``meteo_lectura``: salida de ``sanear_meteo`` (desde el Excel con ``leer_meteo`` o desde la API
  con ``app.integraciones.weatherlink.conversion.lecturas_saneadas``).
- ``phytech_suelo_horario`` / ``phytech_planta_diario``: formato de las hojas ``Suelo_horario`` y
  ``Planta_diario`` (salida de ``limpiar_suelo`` / ``limpiar_planta``).
- ``ndvi_imagen``: una fila por imagen del plot con sus clases (``clases`` jsonb).

Todas devuelven un :class:`ConteoUpsert` y el conjunto de fechas tocadas (para recalcular
``ambiente_diario``). Hacen ``flush``; el commit lo hace quien llama.
"""

from __future__ import annotations

import datetime as dt
import math
from typing import Any

import pandas as pd
from riego_ml.utils.tiempo import norm_text
from sqlalchemy.orm import Session

from app.ml.columnas import METEO_ML_A_BD, NDVI_N_CLASES, PLANTA_MEDICIONES, SUELO_BD_A_ML
from app.models import Fundo
from app.models.enums import OrigenMeteo
from app.repositories import datos_campo as repo
from app.repositories.datos_campo import ConteoUpsert


def _valor(valor: Any) -> Any:
    """NaN/NaT/NA -> None; tipos numpy -> Python."""
    if valor is None or valor is pd.NA or valor is pd.NaT:
        return None
    if isinstance(valor, float) and math.isnan(valor):
        return None
    if hasattr(valor, "item"):
        valor = valor.item()
        if isinstance(valor, float) and math.isnan(valor):
            return None
    return valor


def _misma_finca(serie: pd.Series, fundo: Fundo) -> pd.Series:
    return norm_text(serie) == norm_text(pd.Series([fundo.nombre])).iloc[0]


# --- Meteorología ---------------------------------------------------------------

def guardar_meteo(
    db: Session, fundo: Fundo, lecturas: pd.DataFrame, *, origen: OrigenMeteo,
    corrida_id: int | None, pisar_excel: bool = False,
) -> tuple[ConteoUpsert, set[dt.date]]:
    """``lecturas``: salida de ``sanear_meteo`` (``Fundo``, ``fecha_hora``, ``VARIABLES``).
    Solo se guardan las del fundo indicado. El Excel histórico no se pisa con la API (salvo
    ``pisar_excel``, ver ``repositories.datos_campo.upsert_meteo``)."""
    propias = lecturas[_misma_finca(lecturas["Fundo"], fundo)]
    filas = []
    for registro in propias.to_dict("records"):
        fila = {
            "fundo_id": fundo.id,
            "fecha_hora": pd.Timestamp(registro["fecha_hora"]).to_pydatetime(),
            "origen": origen,
            "corrida_id": corrida_id,
        }
        for columna_ml, columna_bd in METEO_ML_A_BD.items():
            fila[columna_bd] = _valor(registro[columna_ml])
        filas.append(fila)
    fechas = {f["fecha_hora"].date() for f in filas}
    return repo.upsert_meteo(db, filas, pisar_excel=pisar_excel), fechas


# --- Phytech --------------------------------------------------------------------

def guardar_suelo(
    db: Session, fundo: Fundo, horario: pd.DataFrame, *, corrida_id: int | None,
    proteger_con_dato: bool = False,
) -> tuple[ConteoUpsert, set[dt.date]]:
    """``horario`` con el formato de la hoja ``Suelo_horario`` (salida de ``limpiar_suelo``).
    ``proteger_con_dato``: ver ``repositories.datos_campo.upsert_suelo`` (ingesta de la API)."""
    propias = horario[_misma_finca(horario["fundo"], fundo)].copy()
    propias["fecha_hora"] = pd.to_datetime(propias["fecha_hora"], errors="coerce")
    propias = propias.dropna(subset=["fecha_hora"])
    filas = []
    for registro in propias.to_dict("records"):
        fila = {
            "fundo_id": fundo.id,
            "plot_id": int(registro["plot_id"]),
            "project_id": int(registro["project_id"]),
            "fecha_hora": pd.Timestamp(registro["fecha_hora"]).to_pydatetime(),
            "corrida_id": corrida_id,
        }
        for columna_bd, columna_ml in SUELO_BD_A_ML.items():
            valor = _valor(registro.get(columna_ml))
            fila[columna_bd] = bool(valor) if columna_bd == "hay_dato" else valor
        filas.append(fila)
    fechas = {f["fecha_hora"].date() for f in filas}
    return repo.upsert_suelo(db, filas, proteger_con_dato=proteger_con_dato), fechas


def guardar_planta(
    db: Session, fundo: Fundo, planta: pd.DataFrame, *, corrida_id: int | None,
    columnas: tuple[str, ...] = PLANTA_MEDICIONES,
) -> tuple[ConteoUpsert, set[dt.date]]:
    """``planta`` con el formato de ``Planta_diario``. ``columnas``: las mediciones que trae la
    fuente (el Excel histórico no trae ``et_mm`` ni ``lluvia_mm`` y no las borra)."""
    propias = planta[_misma_finca(planta["fundo"], fundo)].copy()
    propias["fecha"] = pd.to_datetime(propias["fecha"], errors="coerce").dt.normalize()
    propias = propias.dropna(subset=["fecha"])
    filas = []
    for registro in propias.to_dict("records"):
        fila = {
            "fundo_id": fundo.id,
            "plot_id": int(registro["plot_id"]),
            "project_id": int(registro["project_id"]),
            "fecha": pd.Timestamp(registro["fecha"]).date(),
            "corrida_id": corrida_id,
        }
        for columna in columnas:
            fila[columna] = _valor(registro.get(columna))
        filas.append(fila)
    fechas = {f["fecha"] for f in filas}
    return repo.upsert_planta(db, filas, columnas), fechas


# --- NDVI -----------------------------------------------------------------------

def clases_ndvi(registro: dict[str, Any]) -> list[dict[str, Any]]:
    """Columnas ``class{k}_*`` de ``NdviImages`` -> lista de clases para ``ndvi_imagen.clases``."""
    clases = []
    for k in range(NDVI_N_CLASES):
        clases.append({
            "clase": k,
            "color": _valor(registro.get(f"class{k}_color")),
            "ndvi_min": _valor(registro.get(f"class{k}_ndvi_min")),
            "ndvi_max": _valor(registro.get(f"class{k}_ndvi_max")),
            "percent": _valor(registro.get(f"class{k}_percent")),
        })
    return clases


def ndvi_medio_imagen(clases: list[dict[str, Any]]) -> float | None:
    """Promedio de los centros de clase ponderado por % (misma fórmula que ``ndvi_diario``)."""
    total = peso = 0.0
    for clase in clases:
        if None in (clase["ndvi_min"], clase["ndvi_max"], clase["percent"]):
            return None
        total += (clase["ndvi_min"] + clase["ndvi_max"]) / 2 * clase["percent"]
        peso += clase["percent"]
    return total / peso if peso else None


def guardar_ndvi(
    db: Session, fundo: Fundo, imagenes: pd.DataFrame, *, area_id: int, plot_id: int,
    corrida_id: int | None,
) -> tuple[ConteoUpsert, set[dt.date]]:
    """``imagenes`` con el formato de ``NdviImages_*`` (una fila por imagen y entidad); se
    guardan las del plot."""
    propias = imagenes[imagenes["entity_id"] == plot_id].copy()
    if "entity_type" in propias:
        propias = propias[propias["entity_type"].astype(str).str.lower() == "plot"]
    propias["fecha"] = pd.to_datetime(propias["date"], errors="coerce").dt.normalize()
    propias = propias.dropna(subset=["fecha", "image_id"]).drop_duplicates("image_id", keep="last")
    filas = []
    for registro in propias.to_dict("records"):
        clases = clases_ndvi(registro)
        no_vegetacion = _valor(registro.get("no_vegetation"))
        filas.append({
            "fundo_id": fundo.id,
            "image_id": str(_valor(registro["image_id"]))[:64],
            "area_id": area_id,
            "plot_id": plot_id,
            "fecha": pd.Timestamp(registro["fecha"]).date(),
            "no_vegetation": None if no_vegetacion is None else bool(no_vegetacion),
            "clases": clases,
            "ndvi_medio": ndvi_medio_imagen(clases),
            "corrida_id": corrida_id,
        })
    fechas = {f["fecha"] for f in filas}
    return repo.upsert_ndvi(db, filas), fechas
