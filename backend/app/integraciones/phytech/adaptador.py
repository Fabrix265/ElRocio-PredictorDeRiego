"""Respuestas de la API de Phytech -> tablas con el formato de ``riego_ml``.

Se reproduce lo que hacía la ruta por archivos (``descargar_phytech.py`` aplanaba el JSON a
Excel y ``riego_ml.sources.phytech_crudo`` lo limpiaba): ``aplanar``/``recorrer`` están portados
de ``descargar_phytech.py`` y la limpieza es la de ``riego_ml`` (``limpiar_suelo``,
``limpiar_planta``), sin cambiar reglas. Lo único propio del adaptador:

- Suelo: la API devuelve las 24 h de cada día aunque no haya lectura (con ``null``). Una hora
  cuenta como dato solo si trae **alguna humedad** (H8); las demás se descartan antes de
  ``limpiar_suelo`` y quedan como hueco (``hay_dato = false``) dentro de la rejilla horaria.
- Planta: ``limpiar_planta`` no conserva ET ni lluvia; se agregan como ``et_mm`` y ``lluvia_mm``.
- Las horas de Phytech ya vienen en hora local (``PHYTECH_HORAS_EN_HORA_LOCAL = True`` en
  ``riego_ml.settings``).
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from typing import Any

import numpy as np
import pandas as pd
from riego_ml.sources.phytech_crudo import PROFUNDIDADES, limpiar_planta, limpiar_suelo

NIVELES_SUELO = ["area_id", "plot_id", "project_id", "date", "hour"]
NIVELES_DIARIO = ["area_id", "plot_id", "project_id", "date"]
COLUMNAS_HUMEDAD = [*(f"{p}.moisture" for p in PROFUNDIDADES), "rootZone.moisture"]
COLUMNAS_ZONA = ["rootZone.moisture", "rootZone.saturation", "rootZone.stressline",
                 "rootZone.rootZoneNormalized"]


def aplanar(d: Any, prefijo: str = "", sep: str = ".") -> dict[str, Any]:
    """Aplana diccionarios anidados; las listas se guardan como texto JSON."""
    salida: dict[str, Any] = {}
    if not isinstance(d, dict):
        return {prefijo or "value": d}
    for k, v in d.items():
        clave = f"{prefijo}{sep}{k}" if prefijo else str(k)
        if isinstance(v, dict):
            salida.update(aplanar(v, clave, sep))
        elif isinstance(v, list):
            salida[clave] = json.dumps(v, ensure_ascii=False)
        else:
            salida[clave] = v
    return salida


def recorrer(nodo: Any, niveles: list[str], ids: dict | None = None) -> Iterator[dict]:
    """Una fila por hoja del JSON anidado (``area → plot → project → date [→ hour]``)."""
    ids = ids or {}
    if len(ids) == len(niveles):
        if isinstance(nodo, list):
            for item in nodo:
                yield {**ids, **aplanar(item)}
        elif isinstance(nodo, dict):
            yield {**ids, **aplanar(nodo)}
        else:
            yield {**ids, "value": nodo}
        return
    if nodo is None:
        yield dict(ids)
        return
    if not isinstance(nodo, dict):
        return
    for k, v in nodo.items():
        yield from recorrer(v, niveles, {**ids, niveles[len(ids)]: k})


def _tabla(payloads: Iterable[Any], niveles: list[str], plot_id: int) -> pd.DataFrame:
    filas = [fila for data in payloads if data for fila in recorrer(data, niveles)]
    df = pd.DataFrame(filas)
    if df.empty:
        return pd.DataFrame(columns=niveles)
    for columna in ("area_id", "plot_id", "project_id"):
        df[columna] = pd.to_numeric(df[columna], errors="coerce")
    df = df.dropna(subset=["plot_id", "project_id"])
    df = df[df["plot_id"] == plot_id].copy()
    df["plot_id"] = df["plot_id"].astype(int)
    df["project_id"] = df["project_id"].astype(int)
    return df.reset_index(drop=True)


def _numericas(df: pd.DataFrame, columnas: Iterable[str]) -> None:
    for columna in columnas:
        if columna not in df.columns:
            df[columna] = np.nan
        df[columna] = pd.to_numeric(df[columna], errors="coerce").astype(float)


# --- Suelo ----------------------------------------------------------------------

def suelo_crudo(payloads: Iterable[Any], plot_id: int) -> tuple[pd.DataFrame, int]:
    """``SoilHourlyData`` -> filas como ``SoilHourlyData_*.xlsx`` (con ``datetime_local``), solo
    las horas con alguna humedad; y cuántas horas se descartaron por venir sin humedad."""
    df = _tabla(payloads, NIVELES_SUELO, plot_id)
    if df.empty:
        return df, 0
    medidas = [c for c in df.columns if c.endswith((".moisture", ".temp", ".pressure"))
               or c.startswith("rootZone.")]
    _numericas(df, [*medidas, *COLUMNAS_HUMEDAD, *COLUMNAS_ZONA])
    df["datetime_local"] = pd.to_datetime(
        df["date"].astype(str) + " " + df["hour"].astype(str), errors="coerce"
    )
    df = df.dropna(subset=["datetime_local"])
    con_humedad = df[COLUMNAS_HUMEDAD].notna().any(axis=1)
    return df[con_humedad].reset_index(drop=True), int((~con_humedad).sum())


def suelo_horario(payloads: list[Any], plot_id: int, fundo: str) -> tuple[pd.DataFrame, int]:
    """Hoja ``Suelo_horario`` (salida de ``limpiar_suelo``) y cuántas horas llegaron sin humedad."""
    crudo, sin_humedad = suelo_crudo(payloads, plot_id)
    if crudo.empty:
        return pd.DataFrame(), sin_humedad
    horario, _ = limpiar_suelo(crudo, fundo, {})
    return horario, sin_humedad


# --- Planta ---------------------------------------------------------------------

COLUMNAS_PLANTA_API = ["ps", "mds", "growth", "fruit size", "fruit growth", "ET", "rain"]


def planta_diario(payloads: Iterable[Any], plot_id: int, fundo: str) -> pd.DataFrame:
    """Hoja ``Planta_diario`` (``limpiar_planta``) + ``et_mm`` y ``lluvia_mm`` de Phytech."""
    crudo = _tabla(payloads, NIVELES_DIARIO, plot_id)
    if crudo.empty:
        return pd.DataFrame()
    _numericas(crudo, COLUMNAS_PLANTA_API)
    planta, _ = limpiar_planta(crudo, fundo)
    if planta.empty:
        return planta
    extra = crudo.assign(fecha=pd.to_datetime(crudo["date"], errors="coerce").dt.normalize())
    extra = (extra.dropna(subset=["fecha"])
             .drop_duplicates(["project_id", "fecha"], keep="last")
             .rename(columns={"ET": "et_mm", "rain": "lluvia_mm"})
             [["project_id", "fecha", "et_mm", "lluvia_mm"]])
    return planta.merge(extra, on=["project_id", "fecha"], how="left")


# --- NDVI -----------------------------------------------------------------------

def imagenes_ndvi(payloads: Iterable[dict[str, Any]]) -> pd.DataFrame:
    """Histogramas de los ZIP -> filas con el formato de ``NdviImages_*.xlsx`` (``class{k}_*``)."""
    filas = []
    for payload in payloads:
        for h in (payload or {}).get("histogramas") or []:
            fila = {k: v for k, v in h.items() if k not in ("classes", "legend", "histogram")}
            for clase in h.get("classes") or []:
                prefijo = f"class{clase.get('class')}"
                fila[f"{prefijo}_color"] = clase.get("color")
                fila[f"{prefijo}_ndvi_min"] = clase.get("ndvi_min")
                fila[f"{prefijo}_ndvi_max"] = clase.get("ndvi_max")
                fila[f"{prefijo}_percent"] = clase.get("percent")
            filas.append(fila)
    df = pd.DataFrame(filas)
    if df.empty:
        return pd.DataFrame(columns=["image_id", "date", "entity_type", "entity_id"])
    df["entity_id"] = pd.to_numeric(df["entity_id"], errors="coerce")
    return df


# --- Pronóstico -----------------------------------------------------------------

def pronostico(payload: Any, plot_id: int) -> pd.DataFrame:
    """``ProjectsClimateForecastData`` -> ``project_id, fecha, t_max, eto_mm, etc_mm, humedad``."""
    df = _tabla([payload], NIVELES_DIARIO, plot_id)
    columnas = ["project_id", "fecha", "t_max", "eto_mm", "etc_mm", "humedad"]
    if df.empty:
        return pd.DataFrame(columns=columnas)
    df = df.rename(columns={"max_temperature": "t_max", "et0": "eto_mm", "etc": "etc_mm",
                            "humidity": "humedad"})
    _numericas(df, ["t_max", "eto_mm", "etc_mm", "humedad"])
    df["fecha"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["fecha"]).drop_duplicates(["project_id", "fecha"], keep="last")
    return df[columnas].reset_index(drop=True)
