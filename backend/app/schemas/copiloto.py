"""Esquemas del copiloto: sugerencias del agente y su resolución."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.deps import MAX_ID_BD

TipoSugerencia = Literal["revisar_equipo", "revisar_datos", "regenerar_plan", "ajustar_riego", "otro"]
EstadoSugerencia = Literal["pendiente", "aprobada", "descartada"]


class SugerenciaEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    modulo_id: int | None = Field(default=None, ge=1, le=MAX_ID_BD,
                                  description="Por defecto el único módulo activo")
    fecha: dt.date = Field(description="Día al que se refiere la sugerencia")
    turno_codigo: str | None = Field(default=None, max_length=10, pattern=r"^[A-Za-z0-9-]+$")
    tipo: TipoSugerencia
    alerta_codigo: str | None = Field(default=None, max_length=40, pattern=r"^[a-z_]+$",
                                      description="Código de la alerta del resumen que la originó")
    titulo: str = Field(min_length=3, max_length=160)
    detalle: str | None = Field(default=None, max_length=2000)

    @field_validator("turno_codigo", "alerta_codigo", "detalle", mode="before")
    @classmethod
    def _vacio_es_nulo(cls, valor: object) -> object:
        # n8n manda "" (o "null") cuando el agente no completa un campo opcional.
        if isinstance(valor, str) and valor.strip().lower() in ("", "null", "none"):
            return None
        return valor


class ResolverEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    comentario: str | None = Field(default=None, max_length=500)


class SugerenciaSalida(BaseModel):
    id: int
    modulo_id: int
    modulo_codigo: str | None
    fecha: dt.date
    turno_codigo: str | None
    tipo: TipoSugerencia
    alerta_codigo: str | None
    titulo: str
    detalle: str | None
    estado: EstadoSugerencia
    propuesta_por: str
    created_at: dt.datetime
    resuelto_por: str | None
    resuelto_at: dt.datetime | None
    comentario_resolucion: str | None


class SugerenciaCreada(SugerenciaSalida):
    duplicada: bool = Field(description="True si ya había una pendiente igual (no se creó otra)")
