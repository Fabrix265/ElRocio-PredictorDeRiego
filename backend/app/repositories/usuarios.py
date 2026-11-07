"""Consultas de usuarios (las reglas viven en ``app.services``)."""

from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Usuario
from app.models.enums import RolUsuario


def _escapar_like(texto: str) -> str:
    return texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def por_id(db: Session, usuario_id: int, *, bloquear: bool = False) -> Usuario | None:
    consulta = select(Usuario).where(Usuario.id == usuario_id)
    if bloquear:
        consulta = consulta.with_for_update()
    return db.scalars(consulta).first()


def por_username(db: Session, username: str) -> Usuario | None:
    return db.scalars(
        select(Usuario).where(func.lower(Usuario.username) == username.strip().lower())
    ).first()


def por_correo(db: Session, correo: str) -> Usuario | None:
    return db.scalars(
        select(Usuario).where(func.lower(Usuario.correo) == correo.strip().lower())
    ).first()


def por_identificador(db: Session, identificador: str) -> Usuario | None:
    """Usuario o correo (recuperación de contraseña)."""
    valor = identificador.strip().lower()
    return db.scalars(
        select(Usuario).where(
            or_(func.lower(Usuario.username) == valor, func.lower(Usuario.correo) == valor)
        ).order_by(Usuario.id)
    ).first()


def listar(
    db: Session, *, q: str | None = None, rol: RolUsuario | None = None, activo: bool | None = None
) -> list[Usuario]:
    consulta = select(Usuario).order_by(func.lower(Usuario.username))
    if q and q.strip():
        patron = f"%{_escapar_like(q.strip())}%"
        consulta = consulta.where(
            or_(
                Usuario.username.ilike(patron, escape="\\"),
                Usuario.nombre.ilike(patron, escape="\\"),
                Usuario.correo.ilike(patron, escape="\\"),
            )
        )
    if rol is not None:
        consulta = consulta.where(Usuario.rol == rol)
    if activo is not None:
        consulta = consulta.where(Usuario.activo == activo)
    return list(db.scalars(consulta))


def admins_activos_bloqueados(db: Session) -> list[int]:
    """IDs de los admin activos, bloqueando sus filas (evita quedar sin admin por carreras)."""
    return list(
        db.scalars(
            select(Usuario.id)
            .where(Usuario.rol == RolUsuario.admin, Usuario.activo.is_(True))
            .order_by(Usuario.id)
            .with_for_update()
        )
    )


def destinatarios_por_rol(db: Session, rol: RolUsuario) -> list[str]:
    return list(
        db.scalars(
            select(Usuario.correo)
            .where(Usuario.rol == rol, Usuario.activo.is_(True), Usuario.correo != "")
            .order_by(Usuario.id)
        )
    )
