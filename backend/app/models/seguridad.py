"""Usuarios, sesiones, recuperación de contraseña, límites, auditoría y cola de correos."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ActualizadoMixin, Base, CreadoMixin, IdMixin
from app.models.enums import (
    ESTADO_CORREO,
    ROL_USUARIO,
    TIPO_INTENTO,
    EstadoCorreo,
    RolUsuario,
    TipoIntento,
)


class Usuario(IdMixin, CreadoMixin, ActualizadoMixin, Base):
    __tablename__ = "usuario"
    __table_args__ = (
        Index("uq_usuario_lower_username", func.lower(text("username")), unique=True),
        Index("uq_usuario_lower_correo", func.lower(text("correo")), unique=True),
    )

    username: Mapped[str] = mapped_column(String(60))
    nombre: Mapped[str] = mapped_column(String(120))
    correo: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))  # argon2id
    rol: Mapped[RolUsuario] = mapped_column(ROL_USUARIO)
    activo: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    # Se incrementa al desactivar, cambiar rol o contraseña: invalida los access token emitidos.
    token_version: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    debe_cambiar_password: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    ultimo_acceso_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_cambiada_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    creado_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), index=True
    )


class SesionRefresh(IdMixin, CreadoMixin, Base):
    """Refresh token rotativo (solo se guarda su SHA-256). ``familia`` agrupa las rotaciones."""

    __tablename__ = "sesion_refresh"

    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    familia: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revocado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reemplazado_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sesion_refresh.id", ondelete="SET NULL"), index=True
    )
    reemplazado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class PasswordReset(IdMixin, CreadoMixin, Base):
    """Token de recuperación de un solo uso (solo se guarda su SHA-256)."""

    __tablename__ = "password_reset"

    usuario_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expira_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    usado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip: Mapped[str | None] = mapped_column(String(64))


class IntentoLogin(IdMixin, CreadoMixin, Base):
    """Intentos de login / recuperar / restablecer para los límites de §7."""

    __tablename__ = "intento_login"
    __table_args__ = (
        Index("ix_intento_login_tipo_ip_created_at", "tipo", "ip", "created_at"),
        Index("ix_intento_login_tipo_username_created_at", "tipo", "username_intentado", "created_at"),
    )

    tipo: Mapped[TipoIntento] = mapped_column(TIPO_INTENTO)
    username_intentado: Mapped[str | None] = mapped_column(String(254))
    ip: Mapped[str | None] = mapped_column(String(64))
    exito: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)


class Auditoria(IdMixin, Base):
    """Registro de solo inserción (triggers rechazan UPDATE, DELETE y TRUNCATE)."""

    __tablename__ = "auditoria"
    __table_args__ = (Index("ix_auditoria_entidad_entidad_id", "entidad", "entidad_id"),)

    ocurrido_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuario.id"), index=True)
    # Copia del usuario y rol al momento de la acción ("sistema" para la CLI y tareas).
    username: Mapped[str | None] = mapped_column(String(60))
    rol: Mapped[str | None] = mapped_column(String(20))
    accion: Mapped[str] = mapped_column(String(60), index=True)
    entidad: Mapped[str] = mapped_column(String(60))
    entidad_id: Mapped[str | None] = mapped_column(String(60))
    detalle: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(512))


class NotificacionCorreo(IdMixin, CreadoMixin, Base):
    """Cola de correos y registro de envíos. ``contexto`` nunca lleva secretos."""

    __tablename__ = "notificacion_correo"
    __table_args__ = (
        Index("ix_notificacion_correo_estado_proximo_intento_at", "estado", "proximo_intento_at"),
    )

    tipo: Mapped[str] = mapped_column(String(40))
    # Destinatario directo (p. ej. recuperación de contraseña).
    usuario_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="CASCADE"), index=True
    )
    cronograma_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cronograma.id"), index=True
    )
    rol_destino: Mapped[RolUsuario | None] = mapped_column(ROL_USUARIO)
    # Se resuelven al enviar (usuarios activos con ese rol y correo).
    destinatarios: Mapped[list[str] | None] = mapped_column(JSONB)
    asunto: Mapped[str] = mapped_column(String(255))
    contexto: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    estado: Mapped[EstadoCorreo] = mapped_column(
        ESTADO_CORREO, server_default=EstadoCorreo.pendiente.value, default=EstadoCorreo.pendiente
    )
    intentos: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    proximo_intento_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    bloqueado_hasta: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ultimo_error: Mapped[str | None] = mapped_column(Text)
    enviado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
