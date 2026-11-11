"""Consultas de la cola de correos (``notificacion_correo``)."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from app.models import NotificacionCorreo
from app.models.enums import EstadoCorreo


def reclamar_lote(db: Session, ahora: datetime, bloqueo_hasta: datetime, limite: int) -> list[int]:
    """Pasa a ``enviando`` (con ``FOR UPDATE SKIP LOCKED``) un lote listo para enviar."""
    candidatos = (
        select(NotificacionCorreo.id)
        .where(
            or_(
                (NotificacionCorreo.estado == EstadoCorreo.pendiente)
                & (NotificacionCorreo.proximo_intento_at <= ahora),
                (NotificacionCorreo.estado == EstadoCorreo.enviando)
                & (NotificacionCorreo.bloqueado_hasta < ahora),
            )
        )
        .order_by(NotificacionCorreo.proximo_intento_at, NotificacionCorreo.id)
        .limit(limite)
        .with_for_update(skip_locked=True)
    )
    return list(
        db.scalars(
            update(NotificacionCorreo)
            .where(NotificacionCorreo.id.in_(candidatos.scalar_subquery()))
            .values(estado=EstadoCorreo.enviando, bloqueado_hasta=bloqueo_hasta)
            .returning(NotificacionCorreo.id)
            .execution_options(synchronize_session=False)
        )
    )


def por_id_actualizado(db: Session, notificacion_id: int) -> NotificacionCorreo | None:
    """La notificación releída de la BD (no la copia en memoria de la sesión)."""
    return db.get(NotificacionCorreo, notificacion_id, populate_existing=True)
