#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dataset.py
================
Une las tres fuentes confiables en un dataset por ciclo de riego.

Fuentes
-------
- data_riego.xlsx, hoja MOD5       : riego real. Cada registro es un ciclo.
- data_metereologica.xlsx, Sheet1  : meteo cada 30 min; se agrega a diario.
- data_phytech.xlsx                : suelo y planta del sensor 907557
                                     (proyecto conectado a la valvula 21828).

El sensor 930109 (SMP) no se usa: es una sonda adicional, sin valvula y con
calibracion distinta.

Salida
------
ml/data/processed/dataset_riego_MOD5.xlsx
    Dataset           : una fila por ciclo, con nulos conservados.
    Resumen_turno_dia : una fila por turno-dia (cuantos ciclos hubo).
    Resumen_dia       : una fila por fecha (total de ciclos y turnos).
    Resumen           : diagnostico de la union.
    Diccionario       : descripcion de columnas y unidades.

Uso
---
    python ml/src/riego_ml/pipelines/build_dataset.py
    python ml/src/riego_ml/pipelines/build_dataset.py --salida mi_dataset.xlsx
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ML_ROOT = Path(__file__).resolve().parents[3]
RAW_DIR = ML_ROOT / "data" / "raw"

DEFAULT_RIEGO = RAW_DIR / "data_riego.xlsx"
DEFAULT_METEO = RAW_DIR / "data_metereologica.xlsx"
DEFAULT_PHYTECH = RAW_DIR / "data_phytech.xlsx"
DEFAULT_SALIDA = ML_ROOT / "data" / "processed" / "dataset_riego_MOD5.xlsx"

PROJECT_ID = 907557
PHYTECH_VALVE = 21828

SOIL_COLUMNS = [
    "hum_15cm",
    "hum_30cm",
    "hum_45cm",
    "hum_60cm",
    "hum_75cm",
    "hum_90cm",
    "hum_zona_radicular",
]
PLANT_COLUMNS = [
    "mds_contraccion_um",
    "crecimiento_tronco_um",
    "estres_planta_ps",
]
METEO_COLUMNS = [
    "T_mean",
    "T_max",
    "T_min",
    "HR_mean",
    "HR_max",
    "ETO",
    "DPV",
    "Viento",
    "Lluvia",
    "RadSolar_max",
]


def _norm_text(series: pd.Series) -> pd.Series:
    return series.astype("string").str.strip()


def _to_seconds(value: object) -> float:
    """Convierte datetime.time, datetime o texto HH:MM[:SS] a segundos del dia."""
    if value is None:
        return np.nan
    try:
        if pd.isna(value):
            return np.nan
    except (TypeError, ValueError):
        pass

    if isinstance(value, (dt.datetime, pd.Timestamp)):
        return (
            value.hour * 3600
            + value.minute * 60
            + value.second
            + value.microsecond / 1_000_000
        )
    if isinstance(value, dt.time):
        return (
            value.hour * 3600
            + value.minute * 60
            + value.second
            + value.microsecond / 1_000_000
        )

    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none"}:
        return np.nan
    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return np.nan
    return (
        parsed.hour * 3600
        + parsed.minute * 60
        + parsed.second
        + parsed.microsecond / 1_000_000
    )


def load_riego(path: Path, sheet: str = "MOD5") -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet).copy()

    df["Fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.normalize()
    df["Fundo"] = _norm_text(df["Fundo"])
    df["Modulo"] = _norm_text(df["Modulo"])
    df["Turno"] = _norm_text(df["Turno"])
    df["Valvula_SIGA"] = _norm_text(df["Valvula"])

    df["s_ini"] = df["Hora Inicio"].map(_to_seconds)
    df["s_fin"] = df["Hora Fin"].map(_to_seconds)
    df = df.dropna(subset=["Fecha", "Fundo", "Turno", "s_ini", "s_fin"]).copy()

    df["dt_inicio"] = df["Fecha"] + pd.to_timedelta(df["s_ini"], unit="s")
    df["dt_fin"] = df["Fecha"] + pd.to_timedelta(df["s_fin"], unit="s")
    cross_midnight = df["s_fin"] < df["s_ini"]
    df.loc[cross_midnight, "dt_fin"] = df.loc[cross_midnight, "dt_fin"] + pd.Timedelta(days=1)

    df["Duracion_min"] = (df["dt_fin"] - df["dt_inicio"]).dt.total_seconds() / 60.0

    df = df.sort_values(["Fecha", "Turno", "dt_inicio"]).reset_index(drop=True)

    group_keys = ["Fecha", "Turno"]
    df["Ciclo"] = df.groupby(group_keys, sort=False).cumcount() + 1
    df["Ciclos_turno_dia"] = df.groupby(group_keys, sort=False)["Ciclo"].transform("max")

    df["Riego_ciclo_m3"] = pd.to_numeric(
        df["Cantidad de riego (m3)"], errors="coerce"
    )
    df["Riego_ciclo_m3_ha"] = pd.to_numeric(
        df["Cantidad de riego (m3 por hectarea)"], errors="coerce"
    )
    df["Riego_total_turno_m3"] = df.groupby(group_keys, sort=False)[
        "Riego_ciclo_m3"
    ].transform("sum")
    df["Riego_total_turno_m3_ha"] = df.groupby(group_keys, sort=False)[
        "Riego_ciclo_m3_ha"
    ].transform("sum")

    df["Hora_inicio"] = df["dt_inicio"].dt.strftime("%H:%M:%S")
    df["Hora_fin"] = df["dt_fin"].dt.strftime("%H:%M:%S")

    return df


def load_meteo(path: Path, sheet: str = "Sheet1") -> pd.DataFrame:
    df = pd.read_excel(path, sheet_name=sheet, header=2).copy()

    df["Fundo"] = _norm_text(df["Fundo"])
    df["Fecha"] = pd.to_datetime(df["Fecha"], errors="coerce").dt.normalize()
    df = df.dropna(subset=["Fundo", "Fecha"]).copy()

    daily = (
        df.groupby(["Fundo", "Fecha"], as_index=False)
        .agg(
            T_mean=("T° Prom", "mean"),
            T_max=("T° Máx", "max"),
            T_min=("T° Mín", "min"),
            HR_mean=("%HR Prom", "mean"),
            HR_max=("%HR Max", "max"),
            ETO=("ETO", "sum"),
            DPV=("DPV", "mean"),
            Viento=("Viento", "mean"),
            Lluvia=("Lluvia", "sum"),
            RadSolar_max=("Rad Solar Max", "max"),
        )
        .reset_index(drop=True)
    )
    return daily


def load_phytech(
    path: Path, project_id: int = PROJECT_ID
) -> tuple[pd.DataFrame, pd.DataFrame]:
    soil = pd.read_excel(path, sheet_name="Suelo_diario")
    soil = soil[soil["project_id"] == project_id].copy()
    soil["Fundo"] = _norm_text(soil["fundo"])
    soil["Fecha"] = pd.to_datetime(soil["fecha"], errors="coerce").dt.normalize()
    soil = soil.dropna(subset=["Fundo", "Fecha"]).copy()
    soil = soil.rename(
        columns={
            "hum_15cm_media": "hum_15cm",
            "hum_30cm_media": "hum_30cm",
            "hum_45cm_media": "hum_45cm",
            "hum_60cm_media": "hum_60cm",
            "hum_75cm_media": "hum_75cm",
            "hum_90cm_media": "hum_90cm",
            "hum_zona_radicular_media": "hum_zona_radicular",
        }
    )
    soil = soil[["Fundo", "Fecha", *SOIL_COLUMNS]].drop_duplicates(
        ["Fundo", "Fecha"], keep="last"
    )

    plant = pd.read_excel(path, sheet_name="Planta_diario")
    plant = plant[plant["project_id"] == project_id].copy()
    plant["Fundo"] = _norm_text(plant["fundo"])
    plant["Fecha"] = pd.to_datetime(plant["fecha"], errors="coerce").dt.normalize()
    plant = plant.dropna(subset=["Fundo", "Fecha"]).copy()
    plant = plant[["Fundo", "Fecha", *PLANT_COLUMNS]].drop_duplicates(
        ["Fundo", "Fecha"], keep="last"
    )

    return soil, plant


def build_dataset(
    riego: pd.DataFrame,
    meteo: pd.DataFrame,
    soil: pd.DataFrame,
    plant: pd.DataFrame,
) -> pd.DataFrame:
    out = riego.merge(
        meteo, on=["Fundo", "Fecha"], how="left", validate="many_to_one"
    )
    out = out.merge(
        soil, on=["Fundo", "Fecha"], how="left", validate="many_to_one"
    )
    out = out.merge(
        plant, on=["Fundo", "Fecha"], how="left", validate="many_to_one"
    )

    out["Fecha_fin"] = out["dt_fin"].dt.normalize()
    out["tiene_meteo"] = out["T_mean"].notna()
    out["tiene_suelo"] = out[SOIL_COLUMNS].notna().any(axis=1)
    out["tiene_planta"] = out[PLANT_COLUMNS].notna().any(axis=1)

    return out


def build_turno_dia(df: pd.DataFrame) -> pd.DataFrame:
    keys = ["Fecha", "Fundo", "Modulo", "Turno"]
    first_columns = {c: (c, "first") for c in [*METEO_COLUMNS, *SOIL_COLUMNS, *PLANT_COLUMNS]}

    turno = (
        df.groupby(keys, as_index=False)
        .agg(
            Ciclos_turno_dia=("Ciclo", "max"),
            Fecha_inicio=("dt_inicio", "min"),
            Fecha_fin=("dt_fin", "max"),
            Duracion_total_min=("Duracion_min", "sum"),
            Riego_total_turno_m3=("Riego_ciclo_m3", "sum"),
            Riego_total_turno_m3_ha=("Riego_ciclo_m3_ha", "sum"),
            Valvula_SIGA=("Valvula_SIGA", "first"),
            tiene_meteo=("tiene_meteo", "max"),
            tiene_suelo=("tiene_suelo", "max"),
            tiene_planta=("tiene_planta", "max"),
            **first_columns,
        )
        .reset_index(drop=True)
    )

    turno["Hora_inicio"] = turno["Fecha_inicio"].dt.strftime("%H:%M:%S")
    turno["Hora_fin"] = turno["Fecha_fin"].dt.strftime("%H:%M:%S")

    columns = [
        *keys,
        "Ciclos_turno_dia",
        "Valvula_SIGA",
        "Fecha_inicio",
        "Hora_inicio",
        "Fecha_fin",
        "Hora_fin",
        "Duracion_total_min",
        "Riego_total_turno_m3",
        "Riego_total_turno_m3_ha",
        *METEO_COLUMNS,
        *SOIL_COLUMNS,
        *PLANT_COLUMNS,
        "tiene_meteo",
        "tiene_suelo",
        "tiene_planta",
    ]
    return turno[columns]


def build_resumen_dia(turno: pd.DataFrame) -> pd.DataFrame:
    dia = (
        turno.groupby("Fecha", as_index=False)
        .agg(
            Turnos=("Turno", "nunique"),
            Ciclos=("Ciclos_turno_dia", "sum"),
            Riego_total_m3=("Riego_total_turno_m3", "sum"),
            Riego_promedio_m3_ha=("Riego_total_turno_m3_ha", "mean"),
        )
        .reset_index(drop=True)
    )
    return dia


def build_resumen(df: pd.DataFrame, turno: pd.DataFrame, dia: pd.DataFrame) -> pd.DataFrame:
    rows = [
        ("Ciclos totales", len(df)),
        ("Turno-dias", len(turno)),
        ("Dias", len(dia)),
        ("Fecha minima", df["Fecha"].min()),
        ("Fecha maxima", df["Fecha"].max()),
        ("Fundos", ", ".join(sorted(df["Fundo"].dropna().unique().tolist()))),
        ("Modulos", ", ".join(sorted(df["Modulo"].dropna().unique().tolist()))),
        ("Turnos", ", ".join(sorted(df["Turno"].dropna().unique().tolist()))),
        ("Sensor Phytech", f"{PROJECT_ID} (valvula {PHYTECH_VALVE})"),
        ("Ciclos con meteo", f"{df['tiene_meteo'].mean() * 100:.1f}%"),
        ("Ciclos con suelo", f"{df['tiene_suelo'].mean() * 100:.1f}%"),
        ("Ciclos con planta", f"{df['tiene_planta'].mean() * 100:.1f}%"),
        ("Ciclos con duracion 0", int((df["Duracion_min"] == 0).sum())),
        ("Ciclos con m3/ha 0", int((df["Riego_ciclo_m3_ha"] == 0).sum())),
        ("Ciclos en turno-dia con 4+ ciclos", int((df["Ciclos_turno_dia"] >= 4).sum())),
        ("Ciclos con fin cruzando medianoche", int((df["dt_fin"].dt.date != df["Fecha"].dt.date).sum())),
    ]
    return pd.DataFrame(rows, columns=["Metrica", "Valor"])


def build_diccionario() -> pd.DataFrame:
    rows = [
        ("Fecha", "fecha", "Fecha de inicio del ciclo."),
        ("Fundo", "texto", "Fundo de riego. ENSUEÑO 1."),
        ("Modulo", "texto", "Modulo SIGA. EN01-MOD5."),
        ("Turno", "texto", "Turno de riego. TE01 a TE05."),
        ("Ciclo", "1,2,3...", "Numero de ciclo dentro del turno y dia."),
        ("Ciclos_turno_dia", "conteo", "Cantidad de ciclos del turno en ese dia."),
        ("Hora_inicio", "HH:MM:SS", "Hora de inicio del ciclo."),
        ("Hora_fin", "HH:MM:SS", "Hora de fin del ciclo. Puede ser del dia siguiente."),
        ("Fecha_fin", "fecha", "Fecha de fin del ciclo. Puede ser el dia siguiente."),
        ("Duracion_min", "min", "Duracion del ciclo en minutos."),
        ("Riego_ciclo_m3", "m3", "Volumen del ciclo."),
        ("Riego_ciclo_m3_ha", "m3/ha", "Volumen del ciclo por hectarea."),
        ("Riego_total_turno_m3", "m3", "Volumen total del turno en ese dia."),
        ("Riego_total_turno_m3_ha", "m3/ha", "Volumen total por hectarea del turno en ese dia."),
        ("Valvula_SIGA", "codigo", "Valvula del registro de riego SIGA."),
        ("T_mean", "C", "Temperatura promedio diaria."),
        ("T_max", "C", "Temperatura maxima diaria."),
        ("T_min", "C", "Temperatura minima diaria."),
        ("HR_mean", "%", "Humedad relativa promedio diaria."),
        ("HR_max", "%", "Humedad relativa maxima diaria."),
        ("ETO", "mm", "Evapotranspiracion de referencia acumulada del dia."),
        ("DPV", "kPa", "Deficit de presion de vapor promedio."),
        ("Viento", "m/s", "Velocidad de viento promedio."),
        ("Lluvia", "mm", "Lluvia acumulada del dia."),
        ("RadSolar_max", "W/m2", "Radiacion solar maxima."),
        ("hum_15cm", "%", "Humedad volumetrica a 15 cm. Sensor 907557."),
        ("hum_30cm", "%", "Humedad volumetrica a 30 cm. Sensor 907557."),
        ("hum_45cm", "%", "Humedad volumetrica a 45 cm. Sensor 907557."),
        ("hum_60cm", "%", "Humedad volumetrica a 60 cm. Sensor 907557."),
        ("hum_75cm", "%", "Humedad volumetrica a 75 cm. Sensor 907557."),
        ("hum_90cm", "%", "Humedad volumetrica a 90 cm. Sensor 907557."),
        ("hum_zona_radicular", "%", "Humedad de zona radicular. Sensor 907557."),
        ("mds_contraccion_um", "um", "Maxima contraccion diaria del tronco."),
        ("crecimiento_tronco_um", "um", "Crecimiento diario del tronco."),
        ("estres_planta_ps", "indice", "Indice de estres de planta."),
        ("tiene_meteo", "0/1", "1 si el ciclo tiene meteo para su fecha."),
        ("tiene_suelo", "0/1", "1 si el ciclo tiene suelo para su fecha."),
        ("tiene_planta", "0/1", "1 si el ciclo tiene planta para su fecha."),
        ("Fecha_inicio", "fecha", "Resumen_turno_dia: inicio del primer ciclo del turno."),
        ("Duracion_total_min", "min", "Resumen_turno_dia: suma de duraciones de los ciclos."),
        ("Turnos", "conteo", "Resumen_dia: cantidad de turnos con riego ese dia."),
        ("Ciclos", "conteo", "Resumen_dia: total de ciclos del dia."),
        ("Riego_total_m3", "m3", "Resumen_dia: volumen total de riego del dia."),
        ("Riego_promedio_m3_ha", "m3/ha", "Resumen_dia: promedio de m3/ha entre los turnos del dia."),
    ]
    return pd.DataFrame(rows, columns=["Columna", "Unidad", "Descripcion"])


def write_excel(
    path: Path,
    dataset: pd.DataFrame,
    turno: pd.DataFrame,
    dia: pd.DataFrame,
    resumen: pd.DataFrame,
    diccionario: pd.DataFrame,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(
        path,
        engine="openpyxl",
        datetime_format="yyyy-mm-dd",
        date_format="yyyy-mm-dd",
    ) as writer:
        dataset.to_excel(writer, sheet_name="Dataset", index=False)
        turno.to_excel(writer, sheet_name="Resumen_turno_dia", index=False)
        dia.to_excel(writer, sheet_name="Resumen_dia", index=False)
        resumen.to_excel(writer, sheet_name="Resumen", index=False)
        diccionario.to_excel(writer, sheet_name="Diccionario", index=False)

        header_fill = PatternFill("solid", start_color="1F4E78")
        for sheet in writer.sheets.values():
            for cell in sheet[1]:
                cell.font = Font(bold=True, color="FFFFFF")
                cell.fill = header_fill
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            sheet.freeze_panes = "A2"
            if sheet.title in {"Dataset", "Resumen_turno_dia", "Resumen_dia"}:
                sheet.auto_filter.ref = sheet.dimensions

            for column_cells in sheet.columns:
                width = max(
                    len(str(cell.value)) if cell.value is not None else 0
                    for cell in column_cells
                )
                letter = get_column_letter(column_cells[0].column)
                sheet.column_dimensions[letter].width = min(max(width + 2, 10), 30)


def main() -> None:
    parser = argparse.ArgumentParser(description="Une riego, meteo y Phytech por ciclo.")
    parser.add_argument("--riego", type=Path, default=DEFAULT_RIEGO)
    parser.add_argument("--meteo", type=Path, default=DEFAULT_METEO)
    parser.add_argument("--phytech", type=Path, default=DEFAULT_PHYTECH)
    parser.add_argument("--salida", type=Path, default=DEFAULT_SALIDA)
    parser.add_argument("--project-id", type=int, default=PROJECT_ID)
    args = parser.parse_args()

    print("Leyendo riego...")
    riego = load_riego(args.riego)
    print(f"  ciclos={len(riego)}  turno-dias={riego.groupby(['Fecha', 'Turno']).ngroups}")
    print(f"  rango={riego['Fecha'].min().date()} a {riego['Fecha'].max().date()}")

    print("Leyendo meteo...")
    meteo = load_meteo(args.meteo)
    print(f"  dias={len(meteo)}  rango={meteo['Fecha'].min().date()} a {meteo['Fecha'].max().date()}")

    print(f"Leyendo Phytech (sensor {args.project_id})...")
    soil, plant = load_phytech(args.phytech, args.project_id)
    print(f"  suelo={len(soil)} dias  planta={len(plant)} dias")

    print("Uniendo...")
    dataset = build_dataset(riego, meteo, soil, plant)
    turno = build_turno_dia(dataset)
    dia = build_resumen_dia(turno)
    resumen = build_resumen(dataset, turno, dia)
    diccionario = build_diccionario()

    dataset_out = dataset[
        [
            "Fecha",
            "Fundo",
            "Modulo",
            "Turno",
            "Ciclo",
            "Ciclos_turno_dia",
            "Hora_inicio",
            "Hora_fin",
            "Fecha_fin",
            "Duracion_min",
            "Riego_ciclo_m3",
            "Riego_ciclo_m3_ha",
            "Riego_total_turno_m3",
            "Riego_total_turno_m3_ha",
            "Valvula_SIGA",
            *METEO_COLUMNS,
            *SOIL_COLUMNS,
            *PLANT_COLUMNS,
            "tiene_meteo",
            "tiene_suelo",
            "tiene_planta",
        ]
    ]

    write_excel(args.salida, dataset_out, turno, dia, resumen, diccionario)

    print("\nListo.")
    print(f"  Dataset: {len(dataset_out)} filas x {dataset_out.shape[1]} columnas")
    print(f"  Turno-dias: {len(turno)}")
    print(f"  Dias: {len(dia)}")
    print(f"  Cobertura meteo: {dataset_out['tiene_meteo'].mean() * 100:.1f}%")
    print(f"  Cobertura suelo: {dataset_out['tiene_suelo'].mean() * 100:.1f}%")
    print(f"  Cobertura planta: {dataset_out['tiene_planta'].mean() * 100:.1f}%")
    print(f"  Salida: {args.salida}")


if __name__ == "__main__":
    main()
