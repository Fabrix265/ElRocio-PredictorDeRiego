"""Esquemas de cronogramas (F3: generar, regenerar y lectura)."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.datos import FrescuraSalida


class GenerarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    modulo_id: int = Field(ge=1, le=2**63 - 1)
    fecha_inicio: dt.date | None = None  # por defecto hoy (Lima)
    dias: int = Field(default=3, ge=1, le=7)
    regenerar_existentes: bool = False


class RegenerarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmar: bool = False


class ResultadoDia(BaseModel):
    fecha: dt.date
    accion: str  # creado · regenerado · omitido
    cronograma_id: int | None = None
    version: int | None = None
    borrador_de_cambios: bool = False
    preliminar: bool | None = None
    datos_incompletos: bool | None = None
    mensaje: str | None = None


class GenerarSalida(BaseModel):
    generacion_id: int
    modulo_id: int
    fecha_inicio: dt.date
    dias: int
    modelo_version: str
    dias_resultado: list[ResultadoDia]
    frescura: FrescuraSalida
    duracion_ms: int | None = None


class CicloSalida(BaseModel):
    ciclo: int
    riego_m3ha: float
    riego_m3: float
    duracion_min: float
    inicio_min: float
    fin_min: float
    hora_inicio: str
    hora_fin: str
    fin_dia_siguiente: bool
    m3ha_p10: float | None = None
    m3ha_p90: float | None = None
    inicio_desde_min: float | None = None
    inicio_hasta_min: float | None = None


class TurnoCronogramaSalida(BaseModel):
    turno_id: int
    turno_codigo: str
    n_ciclos: int
    n_ciclos_modelo: int | None = None
    area_ha: float
    factor_min_por_m3ha: float | None = None
    caudal_m3h: float | None = None
    total_m3ha: float
    total_m3: float
    total_min: float
    ciclos: list[CicloSalida]


class VersionResumen(BaseModel):
    id: int
    numero: int
    origen: str
    creado_at: dt.datetime
    creado_por: str | None = None
    preliminar: bool
    datos_incompletos: bool
    regenerado: bool
    publicada_at: dt.datetime | None = None
    publicada_por: str | None = None
    es_borrador: bool
    es_publicada: bool
    modelo_version: str | None = None
    generacion_id: int | None = None
    motivo_codigo: str | None = None
    motivo_comentario: str | None = None


class VersionDetalle(VersionResumen):
    desactualizado: bool
    turnos: list[TurnoCronogramaSalida]
    total_m3: float


class VersionListado(BaseModel):
    id: int
    numero: int
    origen: str
    creado_at: dt.datetime
    preliminar: bool
    datos_incompletos: bool
    regenerado: bool


class CronogramaCabecera(BaseModel):
    id: int
    modulo_id: int
    modulo_codigo: str
    fecha: dt.date
    estado: str
    lock_version: int
    num_publicaciones: int
    version_publicada_id: int | None = None
    borrador_version_id: int | None = None
    tiene_borrador_cambios: bool
    actualizado_at: dt.datetime


class CronogramaListado(CronogramaCabecera):
    version: VersionListado | None = None


class CronogramaDetalle(CronogramaCabecera):
    version: VersionDetalle | None = None
    versiones: list[VersionResumen]
