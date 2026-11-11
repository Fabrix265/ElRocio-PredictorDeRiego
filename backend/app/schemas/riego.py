"""Esquemas de riego aplicado y de la carga de Excel (§3.5, §4 "Riego aplicado").

Fechas de riego: día de calendario ``AAAA-MM-DD``. Instantes (``*_at``): ISO 8601 con zona.
Los usuarios se devuelven por su ``username`` (nunca hashes ni correos).
"""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import EstadoCarga, EstadoRiego, OrigenRiego, ResultadoCarga

MAX_GRUPOS_PATCH = 100_000
MAX_ID_BD = 2**63 - 1  # bigint (igual que app.api.deps)


class CicloRiegoSalida(BaseModel):
    """Ciclo en minutos desde las 00:00 del día del registro (``fin_min`` puede superar 1440)."""

    model_config = ConfigDict(from_attributes=True)

    inicio_min: float
    fin_min: float
    duracion_min: float
    riego_m3: float | None = None
    riego_m3ha: float | None = None
    area_ha: float | None = None
    valvula: str | None = None
    hora_inicio: str
    hora_fin: str
    fin_dia_siguiente: bool


class RegistroRiegoSalida(BaseModel):
    """Registro (versión) de un turno-día."""

    id: int
    turno_id: int
    turno_codigo: str | None = None
    fecha: dt.date
    version: int
    estado: EstadoRiego
    origen: OrigenRiego
    sin_riego: bool
    motivo: str | None = None
    comentario: str | None = None
    carga_id: int | None = None
    creado_at: dt.datetime | None = None
    creado_por: str | None = None
    ciclos: list[CicloRiegoSalida] = Field(default_factory=list)


class VersionRiegoSalida(RegistroRiegoSalida):
    vigente: bool
    basado_en_id: int | None = None


class CicloRiegoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    inicio_min: float
    duracion_min: float
    riego_m3ha: float


class RegistroRiegoEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    turno_id: int = Field(ge=1, le=MAX_ID_BD)
    fecha: dt.date
    basado_en_id: int | None = Field(default=None, ge=1, le=MAX_ID_BD)
    estado: EstadoRiego
    sin_riego: bool
    motivo: str = Field(min_length=1, max_length=255)
    comentario: str | None = Field(default=None, max_length=1000)
    ciclos: list[CicloRiegoEntrada] = Field(max_length=5)


class RiegoListado(BaseModel):
    modulo_id: int
    desde: dt.date
    hasta: dt.date  # inclusivo
    registros: list[RegistroRiegoSalida]


class GrupoCargaSalida(BaseModel):
    """Turno-día de una carga: qué pasará con él al confirmar."""

    id: int
    fecha: dt.date
    turno_id: int | None = None
    turno_codigo: str | None = None
    resultado: ResultadoCarga
    aplicar: bool
    vigente_id_comparado: int | None = None
    vigente_estado: EstadoRiego | None = None
    vigente_origen: OrigenRiego | None = None
    ciclos: list[CicloRiegoSalida] = Field(default_factory=list)
    mensajes: list[str] = Field(default_factory=list)


class CargaRiegoSalida(BaseModel):
    id: int
    modulo_id: int
    archivo_nombre: str
    sha256: str
    tamano_bytes: int
    subido_at: dt.datetime
    subido_por: str | None = None
    estado: EstadoCarga
    vence_at: dt.datetime
    confirmado_at: dt.datetime | None = None
    confirmado_por: str | None = None
    resumen: dict | None = None
    grupos: list[GrupoCargaSalida] = Field(default_factory=list)


class CambioAplicar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(ge=1, le=MAX_ID_BD)
    aplicar: bool


class CargaMarcar(BaseModel):
    """Marca o desmarca grupos de la vista previa."""

    model_config = ConfigDict(extra="forbid")

    grupos: list[CambioAplicar] = Field(min_length=1, max_length=MAX_GRUPOS_PATCH)


class CargaMarcadaSalida(BaseModel):
    """Selección guardada: solo los grupos solicitados, sin repetir sus ciclos."""

    id: int
    contadores: dict[str, int]
    grupos: list[CambioAplicar]
