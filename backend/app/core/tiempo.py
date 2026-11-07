"""Fechas y horas del sistema.

Toda "fecha de hoy" sale de :func:`hoy_lima` (prohibido ``date.today()`` o ``CURRENT_DATE``):
el servidor puede estar en UTC y a las 19:00 de Lima ya es el día siguiente en UTC.
Los instantes de sistema se manejan en UTC con zona (``timestamptz`` en la BD).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.core.config import settings


@lru_cache
def zona_lima() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def ahora_utc() -> datetime:
    """Instante actual en UTC (con zona)."""
    return datetime.now(timezone.utc)


def a_lima(instante: datetime) -> datetime:
    """Convierte un instante a la hora de Lima. Un ``datetime`` sin zona se toma como UTC."""
    if instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return instante.astimezone(zona_lima())


def ahora_lima() -> datetime:
    return a_lima(ahora_utc())


def hoy_lima() -> date:
    """Fecha de hoy en Lima (zona TIMEZONE, por defecto America/Lima)."""
    return ahora_lima().date()


def inicio_dia_lima(dia: date) -> datetime:
    """00:00 de ``dia`` en Lima, como instante con zona."""
    return datetime(dia.year, dia.month, dia.day, tzinfo=zona_lima())
