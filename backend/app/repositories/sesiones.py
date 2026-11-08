"""Consultas de sesiones de refresh (``sesion_refresh``) y enlaces de recuperación
(``password_reset``). Las reglas viven en ``app.services.auth_service``."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from app.models import PasswordReset, SesionRefresh


# --- Sesiones de refresh --------------------------------------------------------

def inicio_familia(db: Session, familia: uuid.UUID) -> datetime | None:
    """Instante de la primera sesión de la familia (base del tope de duración)."""
    return db.scalar(select(func.min(SesionRefresh.created_at)).where(SesionRefresh.familia == familia))


def por_token_hash(db: Session, token_hash: str, *, bloquear: bool = False) -> SesionRefresh | None:
    consulta = select(SesionRefresh).where(SesionRefresh.token_hash == token_hash)
    if bloquear:
        consulta = consulta.with_for_update()
    return db.scalars(consulta).first()


def revocar_de_usuario(db: Session, usuario_id: int, ahora: datetime) -> None:
    db.execute(
        update(SesionRefresh)
        .where(SesionRefresh.usuario_id == usuario_id, SesionRefresh.revocado_at.is_(None))
        .values(revocado_at=ahora)
        .execution_options(synchronize_session=False)
    )


def revocar_familia(db: Session, familia: uuid.UUID, ahora: datetime) -> None:
    db.execute(
        update(SesionRefresh)
        .where(SesionRefresh.familia == familia, SesionRefresh.revocado_at.is_(None))
        .values(revocado_at=ahora)
        .execution_options(synchronize_session=False)
    )


def familia_activa(db: Session, familia: uuid.UUID, ahora: datetime) -> bool:
    return bool(db.scalar(select(exists().where(
        SesionRefresh.familia == familia,
        SesionRefresh.revocado_at.is_(None),
        SesionRefresh.expira_at > ahora,
    ))))


def revocar_hojas(db: Session, familia: uuid.UUID, ahora: datetime) -> None:
    """Revoca las sesiones vigentes (no reemplazadas) de la familia."""
    db.execute(
        update(SesionRefresh)
        .where(
            SesionRefresh.familia == familia,
            SesionRefresh.revocado_at.is_(None),
            SesionRefresh.reemplazado_por.is_(None),
        )
        .values(revocado_at=ahora)
        .execution_options(synchronize_session=False)
    )


def borrar_sesiones_antiguas(db: Session, limite: datetime) -> int:
    resultado = db.execute(
        delete(SesionRefresh).where(
            or_(SesionRefresh.expira_at < limite, SesionRefresh.revocado_at < limite)
        )
    )
    return resultado.rowcount or 0


# --- Enlaces de recuperación ----------------------------------------------------

def reset_por_token_hash(db: Session, token_hash: str, *, bloquear: bool = False) -> PasswordReset | None:
    consulta = select(PasswordReset).where(PasswordReset.token_hash == token_hash)
    if bloquear:
        consulta = consulta.with_for_update()
    return db.scalars(consulta).first()


def invalidar_resets(db: Session, usuario_id: int, ahora: datetime) -> None:
    """Marca como usados los enlaces pendientes del usuario."""
    db.execute(
        update(PasswordReset)
        .where(PasswordReset.usuario_id == usuario_id, PasswordReset.usado_at.is_(None))
        .values(usado_at=ahora)
        .execution_options(synchronize_session=False)
    )


def borrar_resets_antiguos(db: Session, limite: datetime) -> int:
    resultado = db.execute(
        delete(PasswordReset).where(
            or_(PasswordReset.expira_at < limite, PasswordReset.usado_at < limite)
        )
    )
    return resultado.rowcount or 0
