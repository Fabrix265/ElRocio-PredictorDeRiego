"""Consulta de la auditoría (admin y subgerente, solo lectura)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSesion, requiere_rol
from app.models.enums import RolUsuario
from app.schemas.auditoria import AuditoriaItem, AuditoriaOpciones, AuditoriaPagina
from app.services import auditoria_service
from app.services.auditoria_service import FiltroAuditoria

router = APIRouter(prefix="/auditoria", dependencies=[
    Depends(requiere_rol(RolUsuario.admin, RolUsuario.subgerente)),
])

MAX_PAGE_SIZE = 200


@router.get("", response_model=AuditoriaPagina)
def listar(
    db: DbSesion,
    usuario_id: int | None = None,
    accion: Annotated[str | None, Query(max_length=60)] = None,
    entidad: Annotated[str | None, Query(max_length=60)] = None,
    entidad_id: Annotated[str | None, Query(max_length=60)] = None,
    desde: Annotated[str | None, Query(max_length=40, description="AAAA-MM-DD o ISO 8601")] = None,
    hasta: Annotated[str | None, Query(max_length=40, description="AAAA-MM-DD (incluye el día)")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = 50,
) -> AuditoriaPagina:
    filtro = FiltroAuditoria(
        usuario_id=usuario_id, accion=accion, entidad=entidad, entidad_id=entidad_id,
        desde=desde, hasta=hasta,
    )
    filas, total = auditoria_service.listar(db, filtro, page=page, page_size=page_size)
    return AuditoriaPagina(
        items=[AuditoriaItem.model_validate(f) for f in filas],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/opciones", response_model=AuditoriaOpciones)
def opciones(db: DbSesion) -> dict:
    return auditoria_service.opciones(db)
