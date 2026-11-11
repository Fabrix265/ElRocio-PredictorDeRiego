"""Correos: plantillas HTML/texto (Jinja2) y envío por SMTP o a archivo."""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

DIRECTORIO_PLANTILLAS = Path(__file__).resolve().parent / "templates"

_entorno = Environment(
    loader=FileSystemLoader(DIRECTORIO_PLANTILLAS),
    autoescape=select_autoescape(enabled_extensions=("html",), default_for_string=False),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def renderizar(nombre: str, contexto: dict) -> tuple[str, str | None]:
    """Devuelve ``(html, texto)`` de la plantilla ``nombre`` (``.html`` y, si existe, ``.txt``)."""
    html = _entorno.get_template(f"{nombre}.html").render(**contexto)
    texto = None
    if (DIRECTORIO_PLANTILLAS / f"{nombre}.txt").exists():
        texto = _entorno.get_template(f"{nombre}.txt").render(**contexto)
    return html, texto
