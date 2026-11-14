"""PDF del cronograma con ReportLab (puro Python), en verde y blanco y sin logos inventados.

Las fuentes estándar (Helvetica) cubren Latin-1: tildes, ñ, «·» y «³».
"""

from __future__ import annotations

import io
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.tiempo import ahora_lima

VERDE = colors.HexColor("#2A7042")
VERDE_OSCURO = colors.HexColor("#1B482C")
VERDE_CLARO = colors.HexColor("#EEF6EF")
ARENA = colors.HexColor("#DDD7C9")
TEXTO_2 = colors.HexColor("#5F5849")


def _num(valor: float, decimales: int) -> str:
    return f"{valor:,.{decimales}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def plan_pdf(meta: dict[str, Any], filas: list[dict[str, Any]]) -> bytes:
    from app.services.reportes_service import ETIQUETA_ESTADO, fecha_larga

    salida = io.BytesIO()
    doc = SimpleDocTemplate(
        salida, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
        title=f"Cronograma {meta['modulo']} {meta['fecha']:%d/%m/%Y}", author="Sistema de Plan de Riego",
    )
    titulo = ParagraphStyle("titulo", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=VERDE_OSCURO)
    sub = ParagraphStyle("sub", fontName="Helvetica", fontSize=10, leading=14, textColor=TEXTO_2)
    pie = ParagraphStyle("pie", fontName="Helvetica", fontSize=8, leading=10, textColor=TEXTO_2)

    estado = ETIQUETA_ESTADO.get(meta["estado"], meta["estado"])
    marcas = f" · {', '.join(meta['marcas'])}" if meta["marcas"] else ""
    contenido: list[Any] = [
        Paragraph("Plan de riego · Grupo El Rocío", titulo),
        Spacer(1, 2 * mm),
        Paragraph(f"{meta['fundo']} · {meta['modulo']} · {fecha_larga(meta['fecha']).capitalize()}", sub),
        Paragraph(f"Estado: {estado} · versión v{meta['version']}"
                  f"{'' if meta['publicada'] else ' (sin publicar)'}{marcas}", sub),
        Paragraph(f"Orden: por {meta.get('orden', 'turno')}", sub),
        Spacer(1, 6 * mm),
    ]

    datos = [["Turno", "Ciclo", "Inicio", "Fin", "Duración (min)", "m³/ha", "m³"]]
    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), VERDE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ALIGN", (1, 0), (-1, -1), "CENTER"),
        ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, ARENA),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    turno_previo = None
    par = False
    for f in filas:
        if f["turno"] != turno_previo:
            par, turno_previo = not par, f["turno"]
            etiqueta = f["turno"]
        else:
            etiqueta = ""
        datos.append([etiqueta, f["ciclo"], f["inicio"], f["fin"], _num(f["duracion_min"], 1),
                      _num(f["m3ha"], 2), _num(f["m3"], 1)])
        if par:
            estilos.append(("BACKGROUND", (0, len(datos) - 1), (-1, len(datos) - 1), VERDE_CLARO))
    total_min = sum(f["duracion_min"] for f in filas)
    total_m3 = sum(f["m3"] for f in filas)
    datos.append(["Total", "", "", "", _num(total_min, 1), "", _num(total_m3, 1)])
    estilos += [("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"), ("LINEABOVE", (0, -1), (-1, -1), 0.8, VERDE)]

    tabla = Table(datos, colWidths=[22 * mm, 16 * mm, 22 * mm, 26 * mm, 30 * mm, 22 * mm, 24 * mm], repeatRows=1)
    tabla.setStyle(TableStyle(estilos))
    contenido += [tabla, Spacer(1, 8 * mm),
                  Paragraph(f"Generado el {ahora_lima():%d/%m/%Y %H:%M} (Lima) por {meta['usuario']} · "
                            "Sistema de Plan de Riego", pie)]
    doc.build(contenido)
    return salida.getvalue()
