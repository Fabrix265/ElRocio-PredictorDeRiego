"""Fechas y horas del sistema.

Toda "fecha de hoy" sale de :func:`hoy_lima` (prohibido ``date.today()`` o ``CURRENT_DATE``):
el servidor puede estar en UTC y a las 19:00 de Lima ya es el día siguiente en UTC.
Los instantes de sistema se manejan en UTC con zona (``timestamptz`` en la BD).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
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


# Límites de las fechas que aceptan las consultas y la ingesta: el primer año con datos de las
# estaciones (WeatherLink desde 2017) y, hacia adelante, un año. Fuera de eso es un error de quien
# llama (422), nunca un 500 por desbordar ``date`` al sumar o restar días.
FECHA_MINIMA_DATOS = date(2017, 1, 1)
DIAS_MAXIMOS_FUTURO = 366


def fecha_maxima_consulta() -> date:
    return hoy_lima() + timedelta(days=DIAS_MAXIMOS_FUTURO)


def fuera_de_limites(*fechas: date | None) -> date | None:
    """La primera fecha fuera de ``[FECHA_MINIMA_DATOS, hoy + DIAS_MAXIMOS_FUTURO]``, o ``None``."""
    maxima = fecha_maxima_consulta()
    return next((f for f in fechas if f is not None and not FECHA_MINIMA_DATOS <= f <= maxima), None)


def mensaje_fuera_de_limites() -> str:
    return (f"Las fechas deben estar entre {FECHA_MINIMA_DATOS.isoformat()} y "
            f"{fecha_maxima_consulta().isoformat()}")


def inicio_dia_lima(dia: date) -> datetime:
    """00:00 de ``dia`` en Lima, como instante con zona."""
    return datetime(dia.year, dia.month, dia.day, tzinfo=zona_lima())
