"""Esquemas de auditoría (contrato HTTP de ``/api/v1/auditoria``)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditoriaItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ocurrido_at: datetime
    usuario_id: int | None
    username: str | None
    rol: str | None
    accion: str
    entidad: str
    entidad_id: str | None
    detalle: dict[str, Any] | None
    ip: str | None
    user_agent: str | None


class AuditoriaPagina(BaseModel):
    items: list[AuditoriaItem]
    total: int
    page: int
    page_size: int


class UsuarioOpcion(BaseModel):
    id: int
    username: str
    nombre: str


class AuditoriaOpciones(BaseModel):
    acciones: list[str]
    entidades: list[str]
    usuarios: list[UsuarioOpcion]
