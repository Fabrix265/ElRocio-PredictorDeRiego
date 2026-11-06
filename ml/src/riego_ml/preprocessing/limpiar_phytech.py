#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
limpiar_phytech.py
==================
Toma los Excel crudos descargados de la API de Phytech y genera UN Excel limpio
con la humedad/temperatura del suelo por profundidad y la contracción de la
planta (MDS) de un plot (por defecto ENSUEÑO 1), listo para cuadrar después con
los datos de riego (fecha / fundo / turno) y meteorológicos (fecha / hora / fundo).

USO
---
    python limpiar_phytech.py
    python limpiar_phytech.py --carpeta "C:/ruta/phytech/completo" --salida phytech_limpio.xlsx
    python limpiar_phytech.py --plot-id 70208 --area-id 12537 --fundo "ENSUEÑO 1"

HOJAS DEL EXCEL RESULTANTE
--------------------------
  Suelo_horario  : 1 fila por hora y por sensor. Humedad (%) y temperatura (°C)
                   a 15/30/45/60/75/90 cm + resumen de zona radicular.
  Suelo_diario   : resumen diario por sensor (media/mín/máx de humedad por
                   profundidad, temperatura media). Útil para cruzar con riego.
  Planta_diario  : 1 fila por día. Contracción máxima diaria (MDS), crecimiento
                   del tronco, índice de estrés (ps), fruto.
  Leyenda        : descripción de columnas, reglas de limpieza y diagnóstico.

LLAVES PARA CUADRAR DESPUÉS
---------------------------
  - fundo            (texto, igual al de riego y meteorología: "ENSUEÑO 1")
  - fecha            (fecha sin hora; sirve para unir con riego, que es diario)
  - hora_inicio_h    (hora entera 0-23; Phytech es horario, meteorología es cada
                      30 min, así que se agrupará por hora al cuadrar)
  - fecha_hora       (fecha + hora, hora local de Lima, UTC-5)
  - turno            (vacío por ahora; ver TURNO_DEL_SENSOR más abajo)
"""

import argparse
import glob
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

# ----------------------------------------------------------------------------
# CONFIGURACIÓN (se puede cambiar por línea de comandos)
# ----------------------------------------------------------------------------
ML_ROOT = Path(__file__).resolve().parents[3]
DATA_RAW_DIR = ML_ROOT / "data" / "raw"

CARPETA_DEFAULT = str(DATA_RAW_DIR / "phytech")   # carpeta donde están los Soil/Projects xlsx
AREA_ID_DEFAULT = 12537                # área Phytech "ENSUEÑO 2" (contiene el plot ENSUEÑO 1)
PLOT_ID_DEFAULT = 70208                # plot Phytech "ENSUEÑO 1"
FUNDO_DEFAULT = "ENSUEÑO 1"            # nombre de fundo en tus Excel de riego/meteo
SALIDA_DEFAULT = str(DATA_RAW_DIR / "data_phytech.xlsx")

# Turno de riego (TE01..TE05) donde está instalado el sensor. Phytech NO trae este
# dato (solo conoce la válvula 21828). Si sabes en qué turno está, ponlo aquí y
# la columna 'turno' se llenará sola; si no, queda vacía para llenarla luego.
TURNO_DEL_SENSOR = None                # ejemplo: "TE01"

PROFUNDIDADES = [15, 30, 45, 60, 75, 90]
# Temperatura solo existe físicamente a estas profundidades (45 y 75 vienen 100% vacías)
PROF_CON_TEMP = [15, 30, 60, 90]

# Rangos físicos válidos; fuera de ellos se considera error de sensor -> vacío
HUM_MIN, HUM_MAX = 0.0, 100.0
TEMP_MIN, TEMP_MAX = -5.0, 60.0


# ----------------------------------------------------------------------------
# LECTURA
# ----------------------------------------------------------------------------
def leer_anios(carpeta, prefijo, area_id, plot_id):
    """Lee todos los años de un tipo de archivo y se queda solo con el plot pedido."""
    patron = os.path.join(carpeta, "**", f"{prefijo}_*_area{area_id}.xlsx")
    archivos = sorted(glob.glob(patron, recursive=True))
    if not archivos:
        sys.exit(f"No encontré archivos con el patrón: {patron}")
    partes = []
    for f in archivos:
        df = pd.read_excel(f)
        df = df[df["plot_id"] == plot_id].copy()
        print(f"  {os.path.basename(f):50s} filas del plot: {len(df):6d}")
        if len(df):
            partes.append(df)
    if not partes:
        sys.exit(f"El plot {plot_id} no aparece en {prefijo}")
    # concat tolera que 2022 tenga menos columnas (sin 'pressure')
    return pd.concat(partes, ignore_index=True)


def etiqueta_sensor(carpeta, area_id):
    """Nombre del proyecto (sensor) por project_id, leído de la metadata."""
    patron = os.path.join(carpeta, "**", f"Metadata_projects_area{area_id}.xlsx")
    archivos = sorted(glob.glob(patron, recursive=True))
    if not archivos:
        return {}
    m = pd.read_excel(archivos[0])
    return dict(zip(m["projectId"], m["projectName"].astype(str)))


# ----------------------------------------------------------------------------
# LIMPIEZA
# ----------------------------------------------------------------------------
def limpiar_suelo(raw, fundo, nombres_proyecto):
    diag = {}
    df = raw.copy()
    df["datetime_local"] = pd.to_datetime(df["datetime_local"])

    # 1) duplicados exactos de (sensor, hora)
    antes = len(df)
    df = df.drop_duplicates(["project_id", "datetime_local"], keep="last")
    diag["Filas duplicadas eliminadas"] = antes - len(df)

    # 2) renombrar columnas "15.moisture" -> "hum_15cm", etc.
    ren = {}
    for p in PROFUNDIDADES:
        ren[f"{p}.moisture"] = f"hum_{p}cm"
        ren[f"{p}.temp"] = f"temp_{p}cm"
    ren.update({
        "rootZone.moisture": "hum_zona_radicular",
        "rootZone.saturation": "hum_saturacion",
        "rootZone.stressline": "hum_linea_estres",
        "rootZone.rootZoneNormalized": "hum_zona_radicular_norm_pct",
    })
    df = df.rename(columns=ren)

    # 3) valores fuera de rango físico -> NaN (se cuentan)
    fuera = 0
    for p in PROFUNDIDADES:
        c = f"hum_{p}cm"
        mal = df[c].notna() & ((df[c] < HUM_MIN) | (df[c] > HUM_MAX))
        fuera += int(mal.sum())
        df.loc[mal, c] = np.nan
    for p in PROF_CON_TEMP:
        c = f"temp_{p}cm"
        mal = df[c].notna() & ((df[c] < TEMP_MIN) | (df[c] > TEMP_MAX))
        fuera += int(mal.sum())
        df.loc[mal, c] = np.nan
    diag["Valores fuera de rango físico puestos en vacío"] = fuera

    # 4) reindexar a rejilla horaria completa por sensor -> los huecos quedan visibles
    trozos = []
    for pid, g in df.groupby("project_id"):
        g = g.set_index("datetime_local").sort_index()
        full = pd.date_range(g.index.min().floor("h"), g.index.max().floor("h"), freq="h")
        g2 = g.reindex(full)
        g2["hay_dato_phytech"] = g2["project_id"].notna().astype(int)
        g2["project_id"] = pid
        g2["plot_id"] = g2["plot_id"].fillna(g["plot_id"].iloc[0]).astype(int)
        g2.index.name = "datetime_local"
        trozos.append(g2.reset_index())
        diag[f"Horas sin registro en Phytech (sensor {pid})"] = int((g2["hay_dato_phytech"] == 0).sum())
    df = pd.concat(trozos, ignore_index=True)

    # 5) columnas de llave
    df["fundo"] = fundo
    df["turno"] = TURNO_DEL_SENSOR
    df["fecha"] = df["datetime_local"].dt.normalize()
    df["hora_inicio_h"] = df["datetime_local"].dt.hour
    df["hora"] = df["datetime_local"].dt.strftime("%H:%M")
    df["fecha_hora"] = df["datetime_local"]
    df["sensor"] = df["project_id"].map(nombres_proyecto).fillna("").astype(str)
    df["sensor"] = "P" + df["project_id"].astype(str) + " (" + df["sensor"] + ")"
    df["plot_nombre"] = fundo

    # 6) % de vacíos por columna (diagnóstico)
    cols_val = [f"hum_{p}cm" for p in PROFUNDIDADES] + [f"temp_{p}cm" for p in PROF_CON_TEMP]
    vac = (df.loc[df["hay_dato_phytech"] == 1, cols_val].isna().mean() * 100).round(1)
    diag["% vacío por columna (solo horas con registro)"] = ", ".join(f"{k}={v}" for k, v in vac.items())

    orden = (["fundo", "turno", "plot_id", "project_id", "sensor", "fecha", "hora_inicio_h",
              "hora", "fecha_hora", "hay_dato_phytech"]
             + [f"hum_{p}cm" for p in PROFUNDIDADES]
             + [f"temp_{p}cm" for p in PROF_CON_TEMP]
             + ["hum_zona_radicular", "hum_saturacion", "hum_linea_estres", "hum_zona_radicular_norm_pct"])
    df = df[orden].sort_values(["project_id", "fecha_hora"]).reset_index(drop=True)
    return df, diag


def suelo_diario(h):
    """Resumen diario por sensor a partir del horario."""
    g = h[h["hay_dato_phytech"] == 1].groupby(["fundo", "turno", "plot_id", "project_id", "sensor", "fecha"],
                                                dropna=False)
    agg = {}
    for p in PROFUNDIDADES:
        agg[f"hum_{p}cm_media"] = (f"hum_{p}cm", "mean")
        agg[f"hum_{p}cm_min"] = (f"hum_{p}cm", "min")
        agg[f"hum_{p}cm_max"] = (f"hum_{p}cm", "max")
    for p in PROF_CON_TEMP:
        agg[f"temp_{p}cm_media"] = (f"temp_{p}cm", "mean")
    agg["hum_zona_radicular_media"] = ("hum_zona_radicular", "mean")
    agg["horas_con_dato"] = ("hay_dato_phytech", "sum")
    d = g.agg(**agg).reset_index()
    num = d.select_dtypes("number").columns.difference(["plot_id", "project_id", "horas_con_dato"])
    d[num] = d[num].round(2)
    return d


def limpiar_planta(raw, fundo):
    """Datos diarios de planta (MDS etc.). Solo el proyecto que tiene dendrómetro."""
    d = raw.copy()
    d["fecha"] = pd.to_datetime(d["date"])
    cols = ["ps", "mds", "growth", "fruit size", "fruit growth"]
    # nos quedamos con los proyectos que realmente traen MDS
    con_mds = d.groupby("project_id")["mds"].count()
    pids = con_mds[con_mds > 0].index.tolist()
    d = d[d["project_id"].isin(pids)].copy()
    d = d.drop_duplicates(["project_id", "fecha"], keep="last")
    d = d.rename(columns={
        "ps": "estres_planta_ps",
        "mds": "mds_contraccion_um",
        "growth": "crecimiento_tronco_um",
        "fruit size": "tamano_fruto_mm",
        "fruit growth": "crecimiento_fruto_mm",
    })
    d["fundo"] = fundo
    d["turno"] = TURNO_DEL_SENSOR
    d = d[["fundo", "turno", "plot_id", "project_id", "fecha",
           "mds_contraccion_um", "crecimiento_tronco_um", "estres_planta_ps",
           "tamano_fruto_mm", "crecimiento_fruto_mm"]]
    d = d.sort_values(["project_id", "fecha"]).reset_index(drop=True)
    diag = {"Días con MDS": int(d["mds_contraccion_um"].notna().sum()),
            "Días totales en la hoja": len(d),
            "Proyecto(s) con dendrómetro": ", ".join(map(str, pids))}
    return d, diag


# ----------------------------------------------------------------------------
# EXCEL
# ----------------------------------------------------------------------------
LEYENDA = [
    ("HOJA Suelo_horario", "", ""),
    ("fundo", "texto", "Fundo, igual que en riego y meteorología (llave)."),
    ("turno", "texto", "Turno de riego TE01-TE05. Vacío salvo que se configure TURNO_DEL_SENSOR (llave con riego)."),
    ("plot_id / project_id", "número", "IDs de Phytech. project_id identifica a cada SENSOR; ENSUEÑO 1 tiene 2 sensores distintos."),
    ("sensor", "texto", "Etiqueta legible del sensor: P907557 (1) y P930109 (SMP)."),
    ("fecha", "fecha", "Día, hora local de Lima (UTC-5). Llave con riego (diario) y meteo."),
    ("hora_inicio_h / hora", "0-23 / HH:MM", "Hora de la lectura. Phytech es horario; meteo es cada 30 min -> al cuadrar, agrupar meteo por hora."),
    ("fecha_hora", "fecha-hora", "fecha + hora (llave horaria)."),
    ("hay_dato_phytech", "1/0", "0 = esa hora no llegó de Phytech (fila creada para que el hueco sea visible)."),
    ("hum_15cm ... hum_90cm", "% vol.", "Humedad volumétrica del suelo por profundidad."),
    ("temp_15/30/60/90cm", "°C", "Temperatura del suelo. A 45 y 75 cm el sensor no mide temperatura (venía 100% vacío), por eso no hay columna."),
    ("hum_zona_radicular", "% vol.", "Humedad promedio de zona radicular calculada por Phytech."),
    ("hum_saturacion / hum_linea_estres", "% vol.", "Umbrales de referencia de Phytech (saturación y línea de estrés)."),
    ("hum_zona_radicular_norm_pct", "%", "Zona radicular normalizada por Phytech (100 = saturación)."),
    ("", "", ""),
    ("HOJA Suelo_diario", "", "Media/mín/máx diaria por profundidad y sensor, a partir de Suelo_horario."),
    ("", "", ""),
    ("HOJA Planta_diario", "", ""),
    ("mds_contraccion_um", "µm", "MDS: máxima contracción diaria del tronco (indicador de estrés hídrico). Solo existe a nivel diario."),
    ("crecimiento_tronco_um", "µm", "Crecimiento diario del tronco según dendrómetro."),
    ("estres_planta_ps", "índice", "Índice de estrés de planta que reporta Phytech (columna 'ps')."),
    ("tamano_fruto_mm / crecimiento_fruto_mm", "mm", "Solo en la temporada en que hay sensor de fruto."),
    ("", "", ""),
    ("REGLAS DE LIMPIEZA", "", ""),
    ("1", "", f"Humedad fuera de {HUM_MIN}-{HUM_MAX} % y temperatura fuera de {TEMP_MIN}-{TEMP_MAX} °C se consideran error de sensor y se dejan vacías (no se interpola)."),
    ("2", "", "Se eliminan filas duplicadas (mismo sensor y misma hora)."),
    ("3", "", "Se crea una fila por cada hora entre la primera y la última lectura de cada sensor, aunque Phytech no la haya enviado."),
    ("4", "", "Columnas 100% vacías (pressure en todas las profundidades y temp 45/75) se eliminan."),
    ("5", "", "No se rellenan ni se interpolan valores: lo vacío es vacío."),
]


def estilo_hoja(ws, df, formatos=None, ancho_min=10):
    fill = PatternFill("solid", start_color="1F4E78")
    for c in ws[1]:
        c.font = Font(name="Arial", bold=True, color="FFFFFF", size=10)
        c.fill = fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, col in enumerate(df.columns, start=1):
        letra = get_column_letter(i)
        ws.column_dimensions[letra].width = max(ancho_min, min(24, len(str(col)) + 3))
        fmt = (formatos or {}).get(col)
        if fmt:
            for cel in ws[letra][1:]:
                cel.number_format = fmt
    # fuente uniforme (solo en datos; en hojas muy grandes basta con el formato)
    if ws.max_row < 5000:
        for fila in ws.iter_rows(min_row=2):
            for c in fila:
                c.font = Font(name="Arial", size=10)


def escribir_excel(salida, horario, diario, planta, diag):
    with pd.ExcelWriter(salida, engine="openpyxl", datetime_format="yyyy-mm-dd hh:mm",
                        date_format="yyyy-mm-dd") as xw:
        fm = {"fecha": "yyyy-mm-dd", "fecha_hora": "yyyy-mm-dd hh:mm"}
        horario.to_excel(xw, sheet_name="Suelo_horario", index=False)
        diario.to_excel(xw, sheet_name="Suelo_diario", index=False)
        planta.to_excel(xw, sheet_name="Planta_diario", index=False)
        leyenda = pd.DataFrame(LEYENDA, columns=["Columna / tema", "Unidad", "Descripción"])
        leyenda.to_excel(xw, sheet_name="Leyenda", index=False, startrow=0)
        # diagnóstico debajo de la leyenda
        d = pd.DataFrame(list(diag.items()), columns=["Diagnóstico", "Valor"])
        d.to_excel(xw, sheet_name="Leyenda", index=False, startrow=len(leyenda) + 3)

        estilo_hoja(xw.sheets["Suelo_horario"], horario, fm)
        estilo_hoja(xw.sheets["Suelo_diario"], diario, fm)
        estilo_hoja(xw.sheets["Planta_diario"], planta, fm)
        ws = xw.sheets["Leyenda"]
        for c in ws[1]:
            c.font = Font(name="Arial", bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", start_color="1F4E78")
        for col, w in zip("ABC", (38, 16, 120)):
            ws.column_dimensions[col].width = w
        for fila in ws.iter_rows(min_row=2):
            for c in fila:
                c.font = Font(name="Arial", size=10, bold=str(fila[0].value or "").startswith(("HOJA", "REGLAS")))
        ini = len(leyenda) + 4
        for c in ws[ini]:
            c.font = Font(name="Arial", bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", start_color="1F4E78")
        ws.column_dimensions["B"].width = 16


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Limpia datos crudos de Phytech de un plot.")
    ap.add_argument("--carpeta", default=CARPETA_DEFAULT)
    ap.add_argument("--area-id", type=int, default=AREA_ID_DEFAULT)
    ap.add_argument("--plot-id", type=int, default=PLOT_ID_DEFAULT)
    ap.add_argument("--fundo", default=FUNDO_DEFAULT)
    ap.add_argument("--salida", default=SALIDA_DEFAULT)
    a = ap.parse_args()

    print("Leyendo SoilHourlyData ...")
    soil = leer_anios(a.carpeta, "SoilHourlyData", a.area_id, a.plot_id)
    print("Leyendo ProjectsDailyData ...")
    proj = leer_anios(a.carpeta, "ProjectsDailyData", a.area_id, a.plot_id)

    nombres = etiqueta_sensor(a.carpeta, a.area_id)
    horario, diag_s = limpiar_suelo(soil, a.fundo, nombres)
    diario = suelo_diario(horario)
    planta, diag_p = limpiar_planta(proj, a.fundo)

    diag = {"Fundo": a.fundo, "plot_id Phytech": a.plot_id, "area_id Phytech": a.area_id,
            "Rango Suelo_horario": f"{horario['fecha'].min():%Y-%m-%d} a {horario['fecha'].max():%Y-%m-%d}",
            "Filas Suelo_horario": len(horario), "Filas Suelo_diario": len(diario)}
    diag.update(diag_s)
    diag.update(diag_p)

    escribir_excel(a.salida, horario, diario, planta, diag)
    print(f"\nListo -> {a.salida}")
    for k, v in diag.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
