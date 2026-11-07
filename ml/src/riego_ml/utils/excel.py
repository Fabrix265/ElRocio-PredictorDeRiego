"""Escritura de Excel con un estilo uniforme para todas las salidas del pipeline."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", start_color="1F4E78")
HEADER_FONT = Font(name="Arial", bold=True, color="FFFFFF", size=10)
MAX_WIDTH = 40
SAMPLE_ROWS = 200


def _style_sheet(sheet, frame: pd.DataFrame) -> None:
    for cell in sheet[1]:
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = 30
    sheet.freeze_panes = "A2"
    if len(frame):
        sheet.auto_filter.ref = sheet.dimensions
    for index, column in enumerate(frame.columns, start=1):
        width = len(str(column)) + 2
        if len(frame):
            sample = frame[column].head(SAMPLE_ROWS).astype(str).str.len().max()
            width = max(width, int(sample) + 2)
        sheet.column_dimensions[get_column_letter(index)].width = min(max(width, 10), MAX_WIDTH)


def write_excel(path: str | Path, sheets: dict[str, pd.DataFrame]) -> Path:
    """Escribe varias hojas con cabecera estilizada, filtros y paneles fijos."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(
        target,
        engine="openpyxl",
        datetime_format="yyyy-mm-dd hh:mm",
        date_format="yyyy-mm-dd",
    ) as writer:
        for name, frame in sheets.items():
            frame = frame if not frame.empty else pd.DataFrame({"Mensaje": ["Sin datos"]})
            frame.to_excel(writer, sheet_name=name[:31], index=False)
            _style_sheet(writer.sheets[name[:31]], frame)
    return target


def dict_to_frame(values: dict, key: str = "Metrica", value: str = "Valor") -> pd.DataFrame:
    """Convierte un diccionario de diagnóstico en una tabla de dos columnas."""
    return pd.DataFrame(
        [(k, str(v)) for k, v in values.items()], columns=[key, value]
    )
