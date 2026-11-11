"""``ambiente_diario`` desde la BD (§3.6): recálculo por día afectado con las funciones de riego_ml.

Para cada día se leen **todas** sus lecturas guardadas (meteo de 30 min, suelo horario y planta del
sensor ``PHYTECH_PROJECT_ID``, imágenes NDVI del plot ``PHYTECH_PLOT_ID``) y se arma la fila con
``meteo_diaria``, ``resumir_phytech``, ``ndvi_diario`` y ``construir_ambiente_diario``: las mismas
reglas que la ruta por archivos (test de paridad en ``tests/test_paridad_historico.py``).

- Solo días cerrados (``< hoy_lima()``).
- Un día con solo NDVI se escribe con las banderas en 0.
- Un día sin ningún dato no tiene fila (si la tenía, se borra). La ruta por archivos agrega esos
  días vacíos al calendario, pero ``features_ambiente`` rellena la grilla diaria igual.
- Los servicios hacen ``flush``; el commit lo hace quien llama.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
import pandas as pd
from riego_ml.dataset.unir import CLAVES_DIA, columnas_ambiente, construir_ambiente_diario
from riego_ml.sources.meteo import COLUMNAS_DIARIAS, VARIABLES, meteo_diaria
from riego_ml.sources.ndvi import ndvi_diario
from riego_ml.sources.phytech import resumir_phytech
from riego_ml.utils.tiempo import norm_text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.tiempo import hoy_lima
from app.ml.columnas import (
    AMBIENTE_ML_A_BD,
    BANDERAS_AMBIENTE,
    METEO_BD_A_ML,
    NDVI_N_CLASES,
    PLANTA_MEDICIONES,
    SUELO_BD_A_ML,
)
from app.models import Fundo
from app.repositories import datos_campo as repo

DIAS_POR_TRAMO = 400  # días que se leen de la BD por consulta en recálculos grandes
COLUMNAS_SALIDA = [*CLAVES_DIA, *columnas_ambiente(), *BANDERAS_AMBIENTE]


@dataclass
class ResultadoAmbiente:
    dias: int = 0
    nuevas: int = 0
    actualizadas: int = 0
    sin_cambios: int = 0
    borradas: int = 0


def nombre_fundo(fundo: Fundo) -> str:
    """Texto de ``Fundo`` igual al de los archivos (``norm_text``: sin espacios sobrantes, en
    mayúsculas). Si no coincide con el de los ciclos, el clima queda vacío sin aviso."""
    return str(norm_text(pd.Series([fundo.nombre])).iloc[0])


# --- De la BD a DataFrames con el formato de riego_ml --------------------------

def _lecturas_df(filas, fundo: str) -> pd.DataFrame:
    df = pd.DataFrame(
        [tuple(f) for f in filas], columns=["fecha_hora", *METEO_BD_A_ML.keys()]
    ).rename(columns=METEO_BD_A_ML)
    df.insert(0, "Fundo", fundo)
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
    for columna in VARIABLES:
        df[columna] = pd.to_numeric(df[columna]).astype(float)
    return df


def _horario_df(filas, fundo: str) -> pd.DataFrame:
    columnas_bd = ["project_id", "fecha_hora", *SUELO_BD_A_ML.keys()]
    df = pd.DataFrame([tuple(f) for f in filas], columns=columnas_bd).rename(columns=SUELO_BD_A_ML)
    df.insert(0, "fundo", fundo)
    df["fecha_hora"] = pd.to_datetime(df["fecha_hora"])
    df["hay_dato_phytech"] = df["hay_dato_phytech"].astype(bool).astype(int)
    for columna in df.columns[4:]:
        df[columna] = pd.to_numeric(df[columna]).astype(float)
    return df


def _planta_df(filas, fundo: str) -> pd.DataFrame:
    columnas = ["project_id", "fecha", *repo.COLUMNAS_PLANTA]
    df = pd.DataFrame([tuple(f) for f in filas], columns=columnas)
    df.insert(0, "fundo", fundo)
    df["fecha"] = pd.to_datetime(df["fecha"])
    for columna in PLANTA_MEDICIONES:
        df[columna] = pd.to_numeric(df[columna]).astype(float)
    return df


def imagenes_ndvi_df(imagenes) -> pd.DataFrame:
    """Imágenes de ``ndvi_imagen`` -> columnas del archivo ``NdviImages`` (las que usa
    ``ndvi_diario``)."""
    filas = []
    for imagen in imagenes:
        fila = {"entity_id": imagen.plot_id, "date": pd.Timestamp(imagen.fecha),
                "no_vegetation": imagen.no_vegetation}
        clases = {c.get("clase"): c for c in (imagen.clases or []) if isinstance(c, dict)}
        for k in range(NDVI_N_CLASES):
            clase = clases.get(k, {})
            fila[f"class{k}_ndvi_min"] = clase.get("ndvi_min")
            fila[f"class{k}_ndvi_max"] = clase.get("ndvi_max")
            fila[f"class{k}_percent"] = clase.get("percent")
        filas.append(fila)
    columnas = ["entity_id", "date", "no_vegetation",
                *[f"class{k}_{c}" for k in range(NDVI_N_CLASES) for c in ("ndvi_min", "ndvi_max", "percent")]]
    df = pd.DataFrame(filas, columns=columnas)
    for columna in columnas[3:]:
        df[columna] = pd.to_numeric(df[columna]).astype(float)
    return df


# --- Cálculo (sin BD) -----------------------------------------------------------

def construir_ambiente(
    lecturas: pd.DataFrame, horario: pd.DataFrame, planta: pd.DataFrame, imagenes: pd.DataFrame,
    fundo: str, *, project_id: int, plot_id: int,
) -> pd.DataFrame:
    """Filas de ``ambiente_diario`` (nombres de riego_ml) con las reglas de riego_ml."""
    if lecturas.empty:
        meteo = pd.DataFrame(columns=[*CLAVES_DIA, *COLUMNAS_DIARIAS])
    else:
        meteo, _ = meteo_diaria(lecturas)
    phytech = resumir_phytech(horario, planta, project_id)
    ndvi = ndvi_diario(imagenes, plot_id, fundo)
    ndvi["Fecha"] = pd.to_datetime(ndvi["Fecha"])

    if meteo.empty and phytech.empty:
        ambiente = pd.DataFrame(columns=COLUMNAS_SALIDA)
    else:
        meteo["Fecha"] = pd.to_datetime(meteo["Fecha"])
        ambiente = construir_ambiente_diario(meteo, phytech, ndvi, [fundo])

    solo_ndvi = ndvi[~ndvi["Fecha"].isin(ambiente["Fecha"])]
    if not solo_ndvi.empty:
        extra = pd.DataFrame({c: np.nan for c in COLUMNAS_SALIDA}, index=solo_ndvi.index)
        extra["Fundo"] = solo_ndvi["Fundo"]
        extra["Fecha"] = solo_ndvi["Fecha"]
        extra["ndvi_medio"] = solo_ndvi["ndvi_medio"]
        for bandera in BANDERAS_AMBIENTE:
            extra[bandera] = 0
        partes = [p for p in (ambiente, extra) if not p.empty]
        ambiente = pd.concat(partes, ignore_index=True).sort_values(CLAVES_DIA, kind="stable")
    return ambiente[COLUMNAS_SALIDA].reset_index(drop=True)


def _tiene_datos(ambiente: pd.DataFrame) -> pd.Series:
    valores = ambiente[columnas_ambiente()].notna().any(axis=1)
    banderas = (ambiente[list(BANDERAS_AMBIENTE)].fillna(0).astype(int) == 1).any(axis=1)
    return valores | banderas


def _valor_bd(valor) -> float | None:
    if valor is None or (isinstance(valor, float) and np.isnan(valor)) or pd.isna(valor):
        return None
    return float(valor)


def filas_para_bd(ambiente: pd.DataFrame, fundo_id: int) -> list[dict]:
    filas = []
    for registro in ambiente.to_dict("records"):
        fila = {"fundo_id": fundo_id, "fecha": pd.Timestamp(registro["Fecha"]).date()}
        for columna in columnas_ambiente():
            fila[AMBIENTE_ML_A_BD[columna]] = _valor_bd(registro[columna])
        for bandera in BANDERAS_AMBIENTE:
            fila[bandera] = int(registro[bandera] or 0)
        filas.append(fila)
    return filas


# --- Recálculo ------------------------------------------------------------------

def _tramos(dias: list[dt.date], largo: int) -> list[list[dt.date]]:
    """Agrupa días ordenados en tramos que abarcan como mucho ``largo`` días de calendario."""
    tramos: list[list[dt.date]] = []
    for dia in dias:
        if tramos and (dia - tramos[-1][0]).days < largo:
            tramos[-1].append(dia)
        else:
            tramos.append([dia])
    return tramos


def ambiente_de_dias(
    db: Session, fundo: Fundo, dias: list[dt.date], *, project_id: int, plot_id: int
) -> pd.DataFrame:
    """Calcula (sin guardar) el ambiente de ``dias`` (un tramo) leyendo la BD."""
    desde, hasta = min(dias), max(dias)
    inicio = dt.datetime.combine(desde, dt.time())
    fin = dt.datetime.combine(hasta + dt.timedelta(days=1), dt.time())
    texto_fundo = nombre_fundo(fundo)
    ambiente = construir_ambiente(
        _lecturas_df(repo.lecturas_meteo(db, fundo.id, inicio, fin), texto_fundo),
        _horario_df(repo.suelo_horario(db, project_id, inicio, fin), texto_fundo),
        _planta_df(repo.planta_diario(db, project_id, desde, hasta), texto_fundo),
        imagenes_ndvi_df(repo.ndvi_imagenes(db, fundo.id, plot_id, desde, hasta)),
        texto_fundo, project_id=project_id, plot_id=plot_id,
    )
    pedidos = pd.to_datetime(pd.Series(sorted(set(dias))))
    return ambiente[ambiente["Fecha"].isin(pedidos)].reset_index(drop=True)


def recalcular(
    db: Session, fundo: Fundo, fechas: Iterable[dt.date], *,
    project_id: int | None = None, plot_id: int | None = None,
) -> ResultadoAmbiente:
    """Recalcula y guarda ``ambiente_diario`` de los días cerrados de ``fechas``."""
    project_id = project_id or settings.phytech_project_id
    plot_id = plot_id or settings.phytech_plot_id
    hoy = hoy_lima()
    dias = sorted({f for f in fechas if f < hoy})
    resultado = ResultadoAmbiente(dias=len(dias))
    columnas_valor = [*(AMBIENTE_ML_A_BD[c] for c in columnas_ambiente()), *BANDERAS_AMBIENTE]
    for tramo in _tramos(dias, DIAS_POR_TRAMO):
        ambiente = ambiente_de_dias(db, fundo, tramo, project_id=project_id, plot_id=plot_id)
        ambiente = ambiente[_tiene_datos(ambiente)]
        conteo = repo.upsert_ambiente(db, filas_para_bd(ambiente, fundo.id), columnas_valor)
        resultado.nuevas += conteo.nuevas
        resultado.actualizadas += conteo.actualizadas
        resultado.sin_cambios += conteo.omitidas
        con_fila = {pd.Timestamp(f).date() for f in ambiente["Fecha"]}
        resultado.borradas += repo.borrar_ambiente(db, fundo.id, [d for d in tramo if d not in con_fila])
    db.flush()
    return resultado


def recalcular_todo(db: Session, fundo: Fundo, **kwargs) -> ResultadoAmbiente:
    """Todos los días con alguna lectura guardada (carga histórica)."""
    project_id = kwargs.get("project_id") or settings.phytech_project_id
    plot_id = kwargs.get("plot_id") or settings.phytech_plot_id
    fechas = repo.fechas_con_datos(db, fundo.id, project_id, plot_id)
    return recalcular(db, fundo, fechas, project_id=project_id, plot_id=plot_id)


# --- Lectura para el modelo -----------------------------------------------------

def ambiente_para_modelo(db: Session, fundo: Fundo, *, hasta: dt.date | None = None) -> pd.DataFrame:
    """``ambiente_diario`` con los nombres de riego_ml (``Fundo``, ``Fecha`` datetime64, las 38
    columnas y las banderas), días con ``fecha < hasta`` si se indica."""
    filas = repo.ambiente(db, fundo.id, hasta=None if hasta is None else hasta - dt.timedelta(days=1))
    texto_fundo = nombre_fundo(fundo)
    registros = []
    for fila in filas:
        registro = {"Fundo": texto_fundo, "Fecha": pd.Timestamp(fila.fecha)}
        for columna in columnas_ambiente():
            registro[columna] = getattr(fila, AMBIENTE_ML_A_BD[columna])
        for bandera in BANDERAS_AMBIENTE:
            registro[bandera] = int(getattr(fila, bandera) or 0)
        registros.append(registro)
    df = pd.DataFrame(registros, columns=COLUMNAS_SALIDA)
    df["Fundo"] = norm_text(df["Fundo"])
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    for columna in columnas_ambiente():
        df[columna] = pd.to_numeric(df[columna]).astype(float)
    for bandera in BANDERAS_AMBIENTE:
        df[bandera] = df[bandera].astype(int)
    return df
