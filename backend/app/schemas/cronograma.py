"""Esquemas de cronogramas (F3: generar, regenerar y lectura)."""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

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
    ciclo_modelo: int | None = None
    duracion_manual: bool = False
    campos_editados: list[str] = Field(default_factory=list)


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
    visto_version_id: int | None = None
    visto_programador_at: dt.datetime | None = None
    visto_por: str | None = None
    correccion_solicitada_at: dt.datetime | None = None
    correccion_solicitada_por: str | None = None
    correccion_solicitada_motivo: str | None = None


class CicloEdicionEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    ciclo: int
    riego_m3ha: float
    inicio_min: float
    duracion_min: float
    duracion_manual: bool


class TurnoEdicionEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    turno_id: int = Field(ge=1, le=2**63 - 1)
    n_ciclos: int
    ciclos: list[CicloEdicionEntrada] = Field(max_length=5)


class EdicionEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    basada_en_id: int = Field(ge=1, le=2**63 - 1)
    turnos: list[TurnoEdicionEntrada] = Field(min_length=1, max_length=1000)


class GuardarVersionEntrada(EdicionEntrada):
    lock_version: int = Field(ge=1, le=2**31 - 1)
    motivo_codigo: str | None = Field(default=None, max_length=40)
    motivo_comentario: str | None = Field(default=None, max_length=1000)


class PublicarEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lock_version: int = Field(ge=1, le=2**31 - 1)


class VistoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: int = Field(ge=1, le=2**63 - 1)


class SolicitarCorreccionEntrada(VistoEntrada):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    motivo: str = Field(min_length=5, max_length=1000)


class MantenerEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    comentario: str = Field(min_length=5, max_length=1000)


class AvisoSolape(BaseModel):
    turno_id: int
    ciclo: int
    tipo: Literal["solape"] = "solape"
    mensaje: str


class VersionPrevia(BaseModel):
    """VersionDetalle sin identificador ni número; todavía no se ha guardado."""

    origen: str
    creado_at: dt.datetime
    creado_por: str | None = None
    preliminar: bool
    datos_incompletos: bool
    regenerado: bool = False
    publicada_at: dt.datetime | None = None
    publicada_por: str | None = None
    es_borrador: bool = True
    es_publicada: bool = False
    modelo_version: str | None = None
    generacion_id: int | None = None
    motivo_codigo: str | None = None
    motivo_comentario: str | None = None
    desactualizado: bool
    turnos: list[TurnoCronogramaSalida]
    total_m3: float
    avisos: list[AvisoSolape]


class CronogramaConAvisos(CronogramaDetalle):
    avisos: list[str] = Field(default_factory=list)


class CambioVersion(BaseModel):
    turno_id: int
    turno_codigo: str
    ciclo: int | None
    campo: str
    antes: Any
    despues: Any


class DiferenciasSalida(BaseModel):
    base: int
    contra: int
    cambios: list[CambioVersion]


class EventoSalida(BaseModel):
    tipo: str
    ocurrido_at: dt.datetime
    usuario: str | None
    version_numero: int | None
    motivo_codigo: str | None
    comentario: str | None
    detalle: dict[str, Any] | None
