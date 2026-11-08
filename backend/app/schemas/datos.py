"""Esquemas de datos de campo: frescura (§3.3), series, ingestas y turnos con caudal reciente."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EstadoFrescura = Literal["verde", "naranja", "informativo"]


# --- Frescura -------------------------------------------------------------------

class TurnoFrescura(BaseModel):
    turno_id: int
    turno_codigo: str
    ultima_fecha: dt.date | None
    huecos: list[dt.date] = Field(default_factory=list)


class FuenteFrescura(BaseModel):
    fuente: str  # riego_aplicado · riego_provisional · weatherlink · phytech_suelo · phytech_planta · ndvi · pronostico
    nombre: str
    ultima_fecha: dt.date | None  # última fecha COMPLETA
    estado: EstadoFrescura
    informativa: bool = False
    huecos: list[dt.date] = Field(default_factory=list)  # días de la ventana sin dato (anteriores a ultima_fecha)
    detalle: str | None = None
    por_turno: list[TurnoFrescura] | None = None


class FrescuraSalida(BaseModel):
    modulo_id: int
    fecha: dt.date
    referencia: dt.date  # D-1 respecto de fecha
    dias: int
    fuentes: list[FuenteFrescura]


# --- Ingestas -------------------------------------------------------------------

class ErrorIngestaSalida(BaseModel):
    tipo: str | None = None
    status_code: int | None = None
    endpoint: str | None = None
    mensaje: str | None = None


class IngestaCorridaSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    fuente: str
    disparo: str
    usuario: str | None = None
    fecha_programada: dt.date | None = None
    desde: dt.date | None = None
    hasta: dt.date | None = None
    inicio_at: dt.datetime
    fin_at: dt.datetime | None = None
    duracion_ms: int | None = None
    estado: str
    filas_nuevas: int
    filas_actualizadas: int
    filas_omitidas: int
    conflictos: int
    errores: list[ErrorIngestaSalida] = Field(default_factory=list)


class PeticionIngesta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fuentes: list[str] | None = Field(default=None, max_length=10, description="Sin fuentes = todas")
    desde: dt.date | None = None
    hasta: dt.date | None = None


# --- Series ---------------------------------------------------------------------

class SerieSalida(BaseModel):
    """Serie de una fuente. ``puntos`` son filas planas (``fecha`` o ``fecha_hora`` + valores en
    las unidades del modelo: °C, %, mm, km, kPa, W/m², µm)."""

    fuente: str
    resolucion: str
    desde: dt.date | None
    hasta: dt.date | None
    capturado_fecha: dt.date | None = None
    unidades: dict[str, str] = Field(default_factory=dict)
    puntos: list[dict[str, Any]]


# --- Turnos ---------------------------------------------------------------------

class TurnoCaudalSalida(BaseModel):
    id: int
    codigo: str
    orden: int
    area_ha: float
    valvula_controlador: str
    valvula_siga: str | None
    caudal_m3h: float | None = Field(description="Mediana de los ciclos aplicados de los últimos 30 días")
    factor_min_por_m3ha: float | None
    ciclos_considerados: int
    ultimo_riego_aplicado: dt.date | None
