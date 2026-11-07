"""Reglas de limpieza del registro de riego y tabla turno-día.

Reglas (cada ciclo descartado queda en ``descartados`` con su motivo):

1. Apertura fallida: duración < ``min_duracion_min`` o volumen <
   ``min_riego_m3ha`` (el controlador registra aperturas de segundos y 0 m3).
2. Duplicado: mismo turno, fecha y hora de inicio.

Después se renumeran los ciclos de cada turno-día por hora de inicio
(``Ciclo`` = 1, 2, ...) y se calcula ``n_ciclos``. Los ciclos que empiezan
antes de que termine el anterior en el mismo turno se marcan con
``solapado = 1`` (se conservan: el volumen sí se aplicó).
"""

from __future__ import annotations

import pandas as pd

from riego_ml.sources.riego import COLUMNAS_RIEGO

CLAVES_TURNO = ["Fundo", "Modulo", "Turno"]
CLAVES_TD = ["Fecha", *CLAVES_TURNO]


def limpiar_ciclos(
    riego: pd.DataFrame, min_duracion_min: float, min_riego_m3ha: float
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    df = riego[COLUMNAS_RIEGO].copy()
    df["Fecha"] = pd.to_datetime(df["Fecha"]).dt.normalize()
    motivo = pd.Series("", index=df.index, dtype="object")

    fallida = (
        df["duracion_min"].isna()
        | df["riego_m3ha"].isna()
        | (df["duracion_min"] < min_duracion_min)
        | (df["riego_m3ha"] < min_riego_m3ha)
    )
    motivo[fallida] = (
        f"Apertura fallida (< {min_duracion_min:g} min o < {min_riego_m3ha:g} m3/ha)"
    )
    duplicado = df.duplicated([*CLAVES_TD, "inicio_min"], keep="first") & ~fallida
    motivo[duplicado] = "Duplicado (mismo turno, fecha e inicio)"

    descartar = motivo != ""
    descartados = df[descartar].assign(motivo=motivo[descartar]).reset_index(drop=True)
    ciclos = df[~descartar].sort_values([*CLAVES_TD, "inicio_min"], kind="stable")
    ciclos = ciclos.reset_index(drop=True)

    grupos = ciclos.groupby(CLAVES_TD, sort=False)
    ciclos["Ciclo"] = grupos.cumcount() + 1
    ciclos["n_ciclos"] = grupos["Ciclo"].transform("max")

    # Solapamiento en tiempo continuo (incluye el último ciclo del día anterior).
    tiempos = ciclos[CLAVES_TURNO].assign(
        _ini=ciclos["Fecha"] + pd.to_timedelta(ciclos["inicio_min"], unit="min"),
        _fin=ciclos["Fecha"] + pd.to_timedelta(ciclos["fin_min"], unit="min"),
    ).sort_values([*CLAVES_TURNO, "_ini"], kind="stable")
    fin_previo = tiempos.groupby(CLAVES_TURNO)["_fin"].shift(1)
    ciclos["solapado"] = (tiempos["_ini"] < fin_previo).reindex(ciclos.index).astype(int)

    diag = {
        "Limpieza: ciclos de entrada": len(df),
        "Limpieza: aperturas fallidas descartadas": int(fallida.sum()),
        "Limpieza: duplicados descartados": int(duplicado.sum()),
        "Limpieza: ciclos válidos": len(ciclos),
        "Limpieza: ciclos solapados con el anterior (se conservan)": int(ciclos["solapado"].sum()),
    }
    return ciclos, descartados, diag


def tabla_turno_dia(ciclos: pd.DataFrame) -> pd.DataFrame:
    """1 fila por turno-día con los totales observados (targets del plan)."""
    td = (
        ciclos.groupby(CLAVES_TD, as_index=False)
        .agg(
            n_ciclos=("Ciclo", "max"),
            riego_total_m3ha=("riego_m3ha", "sum"),
            riego_total_m3=("riego_m3", "sum"),
            duracion_total_min=("duracion_min", "sum"),
            inicio_primer_min=("inicio_min", "min"),
            fin_ultimo_min=("fin_min", "max"),
            area_ha=("area_ha", "median"),
        )
        .sort_values(CLAVES_TD)
        .reset_index(drop=True)
    )
    # Día incompleto: se registraron menos turnos que los habituales del módulo.
    turnos_modulo = td.groupby(["Fundo", "Modulo"])["Turno"].transform("nunique")
    turnos_dia = td.groupby(["Fecha", "Fundo", "Modulo"])["Turno"].transform("nunique")
    td["dia_incompleto"] = (turnos_dia < turnos_modulo).astype(int)
    return td
