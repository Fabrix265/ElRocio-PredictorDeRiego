"""Limpieza de las descargas crudas de la API de Phytech.

Lee los Excel ``SoilHourlyData_<año>_area<id>.xlsx`` y
``ProjectsDailyData_<año>_area<id>.xlsx`` de un área, se queda con un plot y
genera las tablas que luego consume el pipeline:

* ``Suelo_horario``: 1 fila por hora y sensor (humedad y temperatura por
  profundidad + resumen de zona radicular). Las horas sin lectura se crean
  vacías (``hay_dato_phytech = 0``) para que los huecos sean visibles.
* ``Suelo_diario``: media/mín/máx diaria por sensor.
* ``Planta_diario``: MDS, crecimiento de tronco, índice de estrés y fruto.

Reglas de limpieza (no se interpola ni se rellena nada):

1. Duplicados (mismo sensor y misma hora) -> se conserva la última lectura.
2. Lecturas alineadas a la hora entera (``floor('h')``) antes de reindexar.
3. Humedad fuera de [HUM_MIN, HUM_MAX] -> vacío. Valores ~0 % indican sonda
   sin contacto con el suelo, no suelo seco.
4. Temperatura fuera de [TEMP_MIN, TEMP_MAX] -> vacío.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

PROFUNDIDADES = [15, 30, 45, 60, 75, 90]
# A 45 y 75 cm el sensor no mide temperatura (las columnas vienen 100 % vacías).
PROF_CON_TEMP = [15, 30, 60, 90]

HUM_MIN, HUM_MAX = 5.0, 60.0      # % volumétrico físicamente posible en este suelo
TEMP_MIN, TEMP_MAX = 5.0, 45.0    # °C de suelo

HUM_COLS = [f"hum_{p}cm" for p in PROFUNDIDADES]
TEMP_COLS = [f"temp_{p}cm" for p in PROF_CON_TEMP]
ZONA_COLS = [
    "hum_zona_radicular",
    "hum_saturacion",
    "hum_linea_estres",
    "hum_zona_radicular_norm_pct",
]
PLANTA_COLS = [
    "mds_contraccion_um",
    "crecimiento_tronco_um",
    "estres_planta_ps",
    "tamano_fruto_mm",
    "crecimiento_fruto_mm",
]


@dataclass
class PhytechLimpio:
    suelo_horario: pd.DataFrame
    suelo_diario: pd.DataFrame
    planta_diario: pd.DataFrame
    diagnostico: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Lectura
# --------------------------------------------------------------------------- #
def leer_anios(carpeta: Path, prefijo: str, area_id: int, plot_id: int) -> pd.DataFrame:
    """Concatena todos los años de un tipo de archivo y filtra el plot pedido."""
    patron = os.path.join(str(carpeta), "**", f"{prefijo}_*_area{area_id}.xlsx")
    archivos = sorted(glob.glob(patron, recursive=True))
    if not archivos:
        raise FileNotFoundError(f"No hay archivos con el patrón: {patron}")
    partes = []
    for archivo in archivos:
        df = pd.read_excel(archivo)
        df = df[df["plot_id"] == plot_id]
        if len(df):
            partes.append(df)
    if not partes:
        raise ValueError(f"El plot {plot_id} no aparece en los archivos {prefijo}.")
    # concat tolera que algunos años traigan menos columnas
    return pd.concat(partes, ignore_index=True)


def nombres_sensores(carpeta: Path, area_id: int) -> dict[int, str]:
    """project_id -> nombre del proyecto (sensor) según la metadata."""
    patron = os.path.join(str(carpeta), "**", f"Metadata_projects_area{area_id}.xlsx")
    archivos = sorted(glob.glob(patron, recursive=True))
    if not archivos:
        return {}
    meta = pd.read_excel(archivos[0])
    return dict(zip(meta["projectId"], meta["projectName"].astype(str)))


# --------------------------------------------------------------------------- #
# Limpieza
# --------------------------------------------------------------------------- #
def _anular_fuera_de_rango(df: pd.DataFrame, columnas: list[str], minimo: float, maximo: float) -> int:
    total = 0
    for columna in columnas:
        if columna not in df.columns:
            df[columna] = np.nan
            continue
        malo = df[columna].notna() & ((df[columna] < minimo) | (df[columna] > maximo))
        total += int(malo.sum())
        df.loc[malo, columna] = np.nan
    return total


def limpiar_suelo(raw: pd.DataFrame, fundo: str, sensores: dict[int, str]) -> tuple[pd.DataFrame, dict]:
    diag: dict = {}
    df = raw.copy()
    df["fecha_hora"] = pd.to_datetime(df["datetime_local"], errors="coerce").dt.floor("h")
    df = df.dropna(subset=["fecha_hora"])

    antes = len(df)
    df = df.sort_values(["project_id", "fecha_hora"]).drop_duplicates(
        ["project_id", "fecha_hora"], keep="last"
    )
    diag["Suelo: filas duplicadas eliminadas"] = antes - len(df)

    renombre = {}
    for p in PROFUNDIDADES:
        renombre[f"{p}.moisture"] = f"hum_{p}cm"
        renombre[f"{p}.temp"] = f"temp_{p}cm"
    renombre.update(
        {
            "rootZone.moisture": "hum_zona_radicular",
            "rootZone.saturation": "hum_saturacion",
            "rootZone.stressline": "hum_linea_estres",
            "rootZone.rootZoneNormalized": "hum_zona_radicular_norm_pct",
        }
    )
    df = df.rename(columns=renombre)

    diag["Suelo: humedades fuera de rango anuladas"] = _anular_fuera_de_rango(
        df, HUM_COLS + ["hum_zona_radicular"], HUM_MIN, HUM_MAX
    )
    diag["Suelo: temperaturas fuera de rango anuladas"] = _anular_fuera_de_rango(
        df, TEMP_COLS, TEMP_MIN, TEMP_MAX
    )

    # Rejilla horaria completa por sensor: los huecos quedan como filas vacías.
    trozos = []
    for pid, grupo in df.groupby("project_id"):
        grupo = grupo.set_index("fecha_hora")
        rejilla = pd.date_range(grupo.index.min(), grupo.index.max(), freq="h")
        completo = grupo.reindex(rejilla)
        completo["hay_dato_phytech"] = completo["project_id"].notna().astype(int)
        completo["project_id"] = pid
        completo["plot_id"] = int(grupo["plot_id"].iloc[0])
        completo.index.name = "fecha_hora"
        trozos.append(completo.reset_index())
        diag[f"Suelo: horas sin registro (sensor {pid})"] = int(
            (completo["hay_dato_phytech"] == 0).sum()
        )
    df = pd.concat(trozos, ignore_index=True)

    df["fundo"] = fundo
    df["fecha"] = df["fecha_hora"].dt.normalize()
    df["hora"] = df["fecha_hora"].dt.hour
    etiqueta = df["project_id"].map(sensores).fillna("").astype(str)
    df["sensor"] = "P" + df["project_id"].astype(str) + " (" + etiqueta + ")"

    con_dato = df["hay_dato_phytech"] == 1
    vacios = (df.loc[con_dato, HUM_COLS + TEMP_COLS].isna().mean() * 100).round(1)
    diag["Suelo: % vacío por columna (horas con registro)"] = ", ".join(
        f"{k}={v}" for k, v in vacios.items()
    )

    columnas = [
        "fundo", "plot_id", "project_id", "sensor", "fecha", "hora", "fecha_hora",
        "hay_dato_phytech", *HUM_COLS, *TEMP_COLS, *ZONA_COLS,
    ]
    df = df[columnas].sort_values(["project_id", "fecha_hora"]).reset_index(drop=True)
    return df, diag


def resumir_suelo_diario(horario: pd.DataFrame) -> pd.DataFrame:
    """Media/mín/máx diaria por sensor (solo horas con registro)."""
    grupos = horario[horario["hay_dato_phytech"] == 1].groupby(
        ["fundo", "plot_id", "project_id", "sensor", "fecha"]
    )
    agregados = {}
    for columna in HUM_COLS:
        agregados[f"{columna}_media"] = (columna, "mean")
        agregados[f"{columna}_min"] = (columna, "min")
        agregados[f"{columna}_max"] = (columna, "max")
    for columna in TEMP_COLS:
        agregados[f"{columna}_media"] = (columna, "mean")
    agregados["hum_zona_radicular_media"] = ("hum_zona_radicular", "mean")
    agregados["horas_con_dato"] = ("hay_dato_phytech", "sum")
    diario = grupos.agg(**agregados).reset_index()
    numericas = diario.columns.difference(
        ["fundo", "plot_id", "project_id", "sensor", "fecha", "horas_con_dato"]
    )
    diario[numericas] = diario[numericas].round(2)
    return diario


def limpiar_planta(raw: pd.DataFrame, fundo: str) -> tuple[pd.DataFrame, dict]:
    """Datos diarios de planta, solo de los proyectos que tienen dendrómetro (MDS)."""
    df = raw.copy()
    df["fecha"] = pd.to_datetime(df["date"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["fecha"])
    con_mds = df.groupby("project_id")["mds"].count()
    proyectos = con_mds[con_mds > 0].index.tolist()
    df = df[df["project_id"].isin(proyectos)]
    df = df.sort_values(["project_id", "fecha"]).drop_duplicates(["project_id", "fecha"], keep="last")
    df = df.rename(
        columns={
            "ps": "estres_planta_ps",
            "mds": "mds_contraccion_um",
            "growth": "crecimiento_tronco_um",
            "fruit size": "tamano_fruto_mm",
            "fruit growth": "crecimiento_fruto_mm",
        }
    )
    # MDS es una contracción: debe ser positiva.
    malo = df["mds_contraccion_um"] <= 0
    df.loc[malo, "mds_contraccion_um"] = np.nan
    for columna in PLANTA_COLS:
        if columna not in df.columns:
            df[columna] = np.nan
    df["fundo"] = fundo
    df = df[["fundo", "plot_id", "project_id", "fecha", *PLANTA_COLS]].reset_index(drop=True)
    diag = {
        "Planta: días con MDS": int(df["mds_contraccion_um"].notna().sum()),
        "Planta: días totales": len(df),
        "Planta: MDS <= 0 anulados": int(malo.sum()),
        "Planta: proyecto(s) con dendrómetro": ", ".join(map(str, proyectos)),
    }
    return df, diag


def limpiar_phytech(carpeta: Path, area_id: int, plot_id: int, fundo: str) -> PhytechLimpio:
    """Ejecuta la limpieza completa para un plot."""
    suelo_raw = leer_anios(carpeta, "SoilHourlyData", area_id, plot_id)
    planta_raw = leer_anios(carpeta, "ProjectsDailyData", area_id, plot_id)
    sensores = nombres_sensores(carpeta, area_id)

    horario, diag_suelo = limpiar_suelo(suelo_raw, fundo, sensores)
    diario = resumir_suelo_diario(horario)
    planta, diag_planta = limpiar_planta(planta_raw, fundo)

    diagnostico = {
        "Fundo": fundo,
        "area_id Phytech": area_id,
        "plot_id Phytech": plot_id,
        "Rango Suelo_horario": f"{horario['fecha'].min():%Y-%m-%d} a {horario['fecha'].max():%Y-%m-%d}",
        "Filas Suelo_horario": len(horario),
        "Filas Suelo_diario": len(diario),
        **diag_suelo,
        **diag_planta,
    }
    return PhytechLimpio(horario, diario, planta, diagnostico)


LEYENDA = [
    ("fundo", "texto", "Fundo, igual que en riego y meteorología (llave de unión)."),
    ("plot_id / project_id", "número", "IDs de Phytech. project_id identifica cada sensor del plot."),
    ("sensor", "texto", "Etiqueta legible del sensor, p. ej. P907557 (1)."),
    ("fecha / hora / fecha_hora", "fecha", "Hora local de Lima (UTC-5), alineada a la hora entera."),
    ("hay_dato_phytech", "1/0", "0 = esa hora no llegó de Phytech (fila creada para ver el hueco)."),
    ("hum_15cm ... hum_90cm", "% vol.", f"Humedad volumétrica por profundidad. Fuera de {HUM_MIN}-{HUM_MAX} % se anula."),
    ("temp_15/30/60/90cm", "°C", f"Temperatura del suelo. Fuera de {TEMP_MIN}-{TEMP_MAX} °C se anula."),
    ("hum_zona_radicular", "% vol.", "Humedad promedio de zona radicular calculada por Phytech."),
    ("hum_saturacion / hum_linea_estres", "% vol.", "Umbrales de referencia de Phytech."),
    ("hum_zona_radicular_norm_pct", "%", "Zona radicular normalizada por Phytech (100 = saturación)."),
    ("mds_contraccion_um", "µm", "Máxima contracción diaria del tronco (estrés hídrico)."),
    ("crecimiento_tronco_um", "µm", "Crecimiento diario del tronco."),
    ("estres_planta_ps", "índice", "Índice de estrés de planta de Phytech (columna 'ps')."),
    ("tamano_fruto_mm / crecimiento_fruto_mm", "mm", "Solo en temporadas con sensor de fruto."),
]
