"""Consultas de la auditoría (filtros y opciones de la pantalla)."""

from __future__ import annotations

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.models import Auditoria, Usuario


def pagina(
    db: Session, condiciones: list[ColumnElement[bool]], *, page: int, page_size: int
) -> tuple[list[Auditoria], int]:
    total = db.scalar(select(func.count()).select_from(Auditoria).where(*condiciones)) or 0
    filas = db.scalars(
        select(Auditoria)
        .where(*condiciones)
        .order_by(Auditoria.ocurrido_at.desc(), Auditoria.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return list(filas), total


def acciones_distintas(db: Session) -> set[str]:
    return set(db.scalars(select(Auditoria.accion).distinct()))


def entidades_distintas(db: Session) -> set[str]:
    return set(db.scalars(select(Auditoria.entidad).distinct()))


def usuarios_para_filtro(db: Session) -> list[dict]:
    filas = db.execute(
        select(Usuario.id, Usuario.username, Usuario.nombre).order_by(func.lower(Usuario.username))
    )
    return [{"id": u.id, "username": u.username, "nombre": u.nombre} for u in filas]
