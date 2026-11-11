"""Consultas de catálogos: organización (fundo › módulo › turno) y motivos de corrección."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Fundo, Modulo, MotivoCorreccion


def fundos_con_modulos(db: Session) -> list[Fundo]:
    """Fundos activos con sus módulos y turnos (los inactivos se filtran en el servicio)."""
    return list(
        db.scalars(
            select(Fundo)
            .where(Fundo.activo.is_(True))
            .options(selectinload(Fundo.modulos).selectinload(Modulo.turnos))
            .order_by(Fundo.codigo)
        )
    )


def motivos_activos(db: Session) -> list[MotivoCorreccion]:
    return list(
        db.scalars(
            select(MotivoCorreccion)
            .where(MotivoCorreccion.activo.is_(True))
            .order_by(MotivoCorreccion.orden, MotivoCorreccion.id)
        )
    )
