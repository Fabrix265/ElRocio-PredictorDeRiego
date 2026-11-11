"""Consultas de ``intento_login`` (las reglas del límite viven en ``app.services.rate_limit``)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ColumnElement, delete, func, select, update
from sqlalchemy.orm import Session

from app.models import IntentoLogin
from app.models.enums import TipoIntento


def ultimo_exito(db: Session, tipo: TipoIntento, usuario: str) -> datetime | None:
    return db.scalar(
        select(func.max(IntentoLogin.created_at)).where(
            IntentoLogin.tipo == tipo,
            IntentoLogin.username_intentado == usuario,
            IntentoLogin.exito.is_(True),
        )
    )


def enesimo_reciente(db: Session, condiciones: list[ColumnElement[bool]], n: int) -> datetime | None:
    """``created_at`` del intento n.º ``n`` más reciente que cumple las condiciones."""
    return db.scalar(
        select(IntentoLogin.created_at)
        .where(*condiciones)
        .order_by(IntentoLogin.created_at.desc())
        .offset(n - 1)
        .limit(1)
    )


def borrar(db: Session, intento_id: int) -> None:
    db.execute(delete(IntentoLogin).where(IntentoLogin.id == intento_id))


def marcar_exito(db: Session, intento_id: int) -> None:
    db.execute(
        update(IntentoLogin)
        .where(IntentoLogin.id == intento_id)
        .values(exito=True)
        .execution_options(synchronize_session=False)
    )


def borrar_anteriores(db: Session, limite: datetime) -> int:
    resultado = db.execute(delete(IntentoLogin).where(IntentoLogin.created_at < limite))
    return resultado.rowcount or 0
