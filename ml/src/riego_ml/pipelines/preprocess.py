from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from riego_ml.preprocessing.cleaning import parse_time_to_minutes
from riego_ml.settings import DATA_PROCESSED_DIR

DEFAULT_INPUT = DATA_PROCESSED_DIR / "dataset_riego_MOD5.xlsx"
DEFAULT_OUTPUT = DATA_PROCESSED_DIR / "dataset_riego_MOD5_clean.xlsx"
DEFAULT_START_DATE = "2022-05-20"
DEFAULT_MAX_CYCLES = 4

TRAINING_ENV = [
    "T_mean",
    "T_max",
    "T_min",
    "HR_mean",
    "ETO",
    "DPV",
    "RadSolar_max",
    "hum_45cm",
    "hum_60cm",
    "hum_75cm",
    "hum_90cm",
    "mds_contraccion_um",
    "crecimiento_tronco_um",
    "estres_planta_ps",
]

TRAINING_COLUMNS = [
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
    *TRAINING_ENV,
]

GROUP_KEYS = ["Fecha", "Fundo", "Modulo", "Turno"]

USO_ENTRENAMIENTO = {
    "Fecha": "Sí (identificador)",
    "Fundo": "Sí (identificador)",
    "Modulo": "Sí (identificador)",
    "Turno": "Sí (categórica)",
    "Ciclo": "Sí (slot del ciclo)",
    "Ciclos_turno_dia": "Sí (target N_ciclos)",
    "Hora_inicio": "Sí (target horario)",
    "Hora_fin": "Sí (target horario)",
    "Fecha_fin": "No (derivada)",
    "Duracion_min": "No (se recalcula)",
    "Riego_ciclo_m3": "No (auditoría)",
    "Riego_ciclo_m3_ha": "Sí (target volumen)",
    "Riego_total_turno_m3": "No (auditoría)",
    "Riego_total_turno_m3_ha": "No (auditoría)",
    "Valvula_SIGA": "No (redundante con Turno)",
    "T_mean": "Sí",
    "T_max": "Sí",
    "T_min": "Sí",
    "HR_mean": "Sí",
    "HR_max": "Opcional",
    "ETO": "Sí",
    "DPV": "Sí",
    "Viento": "Opcional",
    "Lluvia": "Opcional",
    "RadSolar_max": "Sí",
    "hum_15cm": "Opcional (imputar)",
    "hum_30cm": "Opcional (imputar)",
    "hum_45cm": "Sí",
    "hum_60cm": "Sí",
    "hum_75cm": "Sí",
    "hum_90cm": "Sí",
    "hum_zona_radicular": "Opcional (imputar)",
    "mds_contraccion_um": "Sí",
    "crecimiento_tronco_um": "Sí",
    "estres_planta_ps": "Sí",
    "tiene_meteo": "No (QA)",
    "tiene_suelo": "No (QA)",
    "tiene_planta": "No (QA)",
}


def _format_reason(mask: pd.Series, reasons: pd.Series, text: str) -> None:
    for index in mask.index[mask]:
        reasons.at[index].append(text)


def _parse_clean(
    raw: pd.DataFrame, start_date: pd.Timestamp, max_cycles: int
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = raw.copy()
    work["Fecha"] = pd.to_datetime(work["Fecha"], errors="coerce").dt.normalize()
    for column in ["Fundo", "Modulo", "Turno"]:
        work[column] = work[column].astype("string").str.strip()

    work["Ciclo"] = pd.to_numeric(work["Ciclo"], errors="coerce")
    work["_orden_original"] = work["Ciclo"]
    work["Riego_ciclo_m3"] = pd.to_numeric(work["Riego_ciclo_m3"], errors="coerce")
    work["Riego_ciclo_m3_ha"] = pd.to_numeric(
        work["Riego_ciclo_m3_ha"], errors="coerce"
    )
    work["Hora_inicio_min"] = work["Hora_inicio"].map(parse_time_to_minutes)
    work["Hora_fin_min"] = work["Hora_fin"].map(parse_time_to_minutes)

    duration = work["Hora_fin_min"] - work["Hora_inicio_min"]
    workload_duration = duration.where(duration >= 0, duration + 24 * 60)
    work["Duracion_min"] = workload_duration

    cross_midnight = work["Hora_fin_min"] < work["Hora_inicio_min"]
    work["Fecha_fin"] = work["Fecha"]
    work.loc[cross_midnight, "Fecha_fin"] = (
        work.loc[cross_midnight, "Fecha"] + pd.Timedelta(days=1)
    )

    reasons = pd.Series([[] for _ in range(len(work))], index=work.index, dtype=object)
    _format_reason(work["Fecha"].isna(), reasons, "Fecha inválida")
    _format_reason(
        work["Fecha"].notna() & (work["Fecha"] < start_date),
        reasons,
        f"Fecha anterior a {start_date.date()}",
    )
    _format_reason(work["Ciclo"].isna(), reasons, "Ciclo inválido")
    _format_reason(
        work["Hora_inicio_min"].isna() | work["Hora_fin_min"].isna(),
        reasons,
        "Hora inválida",
    )
    _format_reason(
        work["Riego_ciclo_m3"].isna()
        | (work["Riego_ciclo_m3"] <= 0)
        | work["Riego_ciclo_m3_ha"].isna()
        | (work["Riego_ciclo_m3_ha"] <= 0),
        reasons,
        "Volumen de riego no positivo",
    )
    _format_reason(
        work["Duracion_min"].isna()
        | (work["Duracion_min"] <= 0)
        | (work["Duracion_min"] > 24 * 60),
        reasons,
        "Duración inválida",
    )

    discard_mask = reasons.map(len) > 0
    discarded = work.loc[discard_mask].copy()
    discarded["Motivo"] = reasons[discard_mask].map("; ".join)
    discarded["Destino"] = "Descartado"

    clean = work.loc[~discard_mask].copy()
    clean = clean.sort_values(
        [*GROUP_KEYS, "Hora_inicio_min", "Hora_fin_min", "_orden_original"],
        kind="mergesort",
    ).reset_index(drop=True)
    clean["Ciclo"] = clean.groupby(GROUP_KEYS, sort=False).cumcount() + 1
    clean["Ciclos_turno_dia"] = clean.groupby(GROUP_KEYS, sort=False)["Ciclo"].transform(
        "max"
    )
    clean["Riego_total_turno_m3"] = clean.groupby(GROUP_KEYS, sort=False)[
        "Riego_ciclo_m3"
    ].transform("sum")
    clean["Riego_total_turno_m3_ha"] = clean.groupby(GROUP_KEYS, sort=False)[
        "Riego_ciclo_m3_ha"
    ].transform("sum")

    duplicated = clean.duplicated([*GROUP_KEYS, "Ciclo"], keep=False)
    if duplicated.any():
        raise ValueError(
            f"Quedaron {int(duplicated.sum())} filas duplicadas por fecha/turno/ciclo."
        )

    training = clean[clean["Ciclos_turno_dia"] <= max_cycles].copy()
    excluded = clean[clean["Ciclos_turno_dia"] > max_cycles].copy()
    excluded["Motivo"] = (
        f"Turno-día con más de {max_cycles} ciclos (solo Dataset completo)"
    )
    excluded["Destino"] = "Solo Dataset completo"

    discarded = pd.concat([discarded, excluded], ignore_index=True, sort=False)
    discarded = discarded.sort_values(
        ["Fecha", "Turno", "Ciclo"], kind="mergesort", na_position="last"
    ).reset_index(drop=True)

    complete_columns = [
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
        "hum_15cm",
        "hum_30cm",
        "hum_45cm",
        "hum_60cm",
        "hum_75cm",
        "hum_90cm",
        "hum_zona_radicular",
        "mds_contraccion_um",
        "crecimiento_tronco_um",
        "estres_planta_ps",
        "tiene_meteo",
        "tiene_suelo",
        "tiene_planta",
    ]
    clean = clean[[c for c in complete_columns if c in clean.columns]]
    training = training[[c for c in TRAINING_COLUMNS if c in training.columns]]
    discarded_columns = [
        "Fecha",
        "Fundo",
        "Modulo",
        "Turno",
        "Ciclo",
        "Ciclos_turno_dia",
        "Hora_inicio",
        "Hora_fin",
        "Duracion_min",
        "Riego_ciclo_m3",
        "Riego_ciclo_m3_ha",
        "Motivo",
        "Destino",
    ]
    discarded = discarded[
        [c for c in discarded_columns if c in discarded.columns]
    ].copy()

    return clean, training, discarded, clean, training


def _turno_dia(training: pd.DataFrame) -> pd.DataFrame:
    keys = GROUP_KEYS
    env_columns = [c for c in TRAINING_ENV if c in training.columns]
    first_columns = {c: (c, "first") for c in env_columns}
    turno = (
        training.sort_values([*keys, "Ciclo"])
        .groupby(keys, as_index=False)
        .agg(
            Ciclos_turno_dia=("Ciclo", "max"),
            Fecha_inicio=("Fecha", "first"),
            Hora_inicio=("Hora_inicio", "first"),
            Fecha_fin=("Fecha_fin", "last"),
            Hora_fin=("Hora_fin", "last"),
            Duracion_total_min=("Duracion_min", "sum"),
            Riego_total_turno_m3=("Riego_ciclo_m3", "sum"),
            Riego_total_turno_m3_ha=("Riego_ciclo_m3_ha", "sum"),
            **first_columns,
        )
        .reset_index(drop=True)
    )
    columns = [
        *keys,
        "Ciclos_turno_dia",
        "Fecha_inicio",
        "Hora_inicio",
        "Fecha_fin",
        "Hora_fin",
        "Duracion_total_min",
        "Riego_total_turno_m3",
        "Riego_total_turno_m3_ha",
        *env_columns,
    ]
    return turno[[c for c in columns if c in turno.columns]]


def _resumen_dia(turno: pd.DataFrame) -> pd.DataFrame:
    return (
        turno.groupby("Fecha", as_index=False)
        .agg(
            Turnos=("Turno", "nunique"),
            Ciclos=("Ciclos_turno_dia", "sum"),
            Riego_total_m3=("Riego_total_turno_m3", "sum"),
            Riego_promedio_m3_ha=("Riego_total_turno_m3_ha", "mean"),
        )
        .reset_index(drop=True)
    )


def _resumen(
    raw: pd.DataFrame,
    complete: pd.DataFrame,
    training: pd.DataFrame,
    discarded: pd.DataFrame,
    turno: pd.DataFrame,
    dia: pd.DataFrame,
    start_date: pd.Timestamp,
    max_cycles: int,
) -> pd.DataFrame:
    rows: list[tuple[str, object]] = [
        ("Filas originales", len(raw)),
        ("Filas descartadas por reglas", int((discarded["Destino"] == "Descartado").sum())),
        ("Filas solo en Dataset completo", int((discarded["Destino"] == "Solo Dataset completo").sum())),
        ("Filas Dataset completo", len(complete)),
        ("Filas Dataset entrenamiento", len(training)),
        ("Turno-días Dataset completo", complete.groupby(GROUP_KEYS).ngroups),
        ("Turno-días Dataset entrenamiento", training.groupby(GROUP_KEYS).ngroups),
        ("Días con riego", len(dia)),
        ("Fecha mínima", complete["Fecha"].min()),
        ("Fecha máxima", complete["Fecha"].max()),
        ("Fecha de inicio de limpieza", start_date),
        ("Máximo de ciclos para entrenamiento", max_cycles),
        ("Fundos", ", ".join(sorted(complete["Fundo"].dropna().unique().tolist()))),
        ("Módulos", ", ".join(sorted(complete["Modulo"].dropna().unique().tolist()))),
        ("Turnos", ", ".join(sorted(complete["Turno"].dropna().unique().tolist()))),
    ]

    for cycles in sorted(complete["Ciclos_turno_dia"].dropna().unique()):
        subset = complete[complete["Ciclos_turno_dia"] == cycles]
        rows.append(
            (
                f"Turno-días con {int(cycles)} ciclos (completo)",
                subset.groupby(GROUP_KEYS).ngroups,
            )
        )
    for cycles in sorted(training["Ciclos_turno_dia"].dropna().unique()):
        subset = training[training["Ciclos_turno_dia"] == cycles]
        rows.append(
            (
                f"Turno-días con {int(cycles)} ciclos (entrenamiento)",
                subset.groupby(GROUP_KEYS).ngroups,
            )
        )

    for column in TRAINING_ENV:
        if column in training.columns:
            coverage = training[column].notna().mean() * 100
            rows.append((f"Cobertura {column}", f"{coverage:.1f}%"))

    return pd.DataFrame(rows, columns=["Métrica", "Valor"])


def _diccionario(raw_dictionary: pd.DataFrame | None) -> pd.DataFrame:
    if raw_dictionary is None or raw_dictionary.empty:
        dictionary = pd.DataFrame(columns=["Columna", "Unidad", "Descripción"])
    else:
        dictionary = raw_dictionary.copy()
        if "Descripcion" in dictionary.columns:
            dictionary = dictionary.rename(columns={"Descripcion": "Descripción"})
    dictionary["Uso_entrenamiento"] = (
        dictionary["Columna"].map(USO_ENTRENAMIENTO).fillna("No")
    )
    return dictionary


def _write_sheet(writer: pd.ExcelWriter, name: str, frame: pd.DataFrame) -> None:
    frame.to_excel(writer, sheet_name=name, index=False)
    sheet = writer.sheets[name]
    header_fill = PatternFill("solid", start_color="1F4E78")
    for cell in sheet[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    for index, column in enumerate(frame.columns, start=1):
        width = max(10, min(32, len(str(column)) + 2))
        if len(frame) > 0:
            sample = frame[column].astype(str).head(50)
            width = max(width, min(32, int(sample.str.len().max()) + 2))
        sheet.column_dimensions[get_column_letter(index)].width = width


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Limpia el dataset por ciclo y genera una hoja lista para entrenar."
    )
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sheet", type=str, default="Dataset")
    parser.add_argument("--start-date", type=str, default=DEFAULT_START_DATE)
    parser.add_argument("--max-cycles", type=int, default=DEFAULT_MAX_CYCLES)
    args = parser.parse_args(argv)

    if args.max_cycles < 1:
        parser.error("--max-cycles debe ser >= 1")

    start_date = pd.Timestamp(args.start_date).normalize()
    with pd.ExcelFile(args.input) as excel:
        raw = pd.read_excel(excel, sheet_name=args.sheet)
        raw_dictionary = (
            pd.read_excel(excel, sheet_name="Diccionario")
            if "Diccionario" in excel.sheet_names
            else None
        )

    clean, training, discarded, complete, training_sheet = _parse_clean(
        raw, start_date, args.max_cycles
    )
    turno = _turno_dia(training_sheet)
    dia = _resumen_dia(turno)
    resumen = _resumen(
        raw,
        complete,
        training_sheet,
        discarded,
        turno,
        dia,
        start_date,
        args.max_cycles,
    )
    diccionario = _diccionario(raw_dictionary)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(
        args.output,
        engine="openpyxl",
        datetime_format="yyyy-mm-dd",
        date_format="yyyy-mm-dd",
    ) as writer:
        _write_sheet(writer, "Dataset", clean)
        _write_sheet(writer, "Dataset_entrenamiento", training_sheet)
        _write_sheet(writer, "Resumen_turno_dia", turno)
        _write_sheet(writer, "Resumen_dia", dia)
        _write_sheet(writer, "Resumen", resumen)
        _write_sheet(writer, "Descartados", discarded)
        _write_sheet(writer, "Diccionario", diccionario)

    print("Limpieza finalizada.")
    print(f"  Entrada: {args.input}")
    print(f"  Salida:  {args.output}")
    print(f"  Dataset completo: {len(complete)} ciclos")
    print(f"  Dataset entrenamiento: {len(training_sheet)} ciclos")
    print(
        "  Turno-días entrenamiento: "
        f"{training_sheet.groupby(GROUP_KEYS).ngroups}"
    )
    print(f"  Descartados: {len(discarded)} registros")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
