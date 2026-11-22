"""Copiloto agrónomo: tokens de servicio del agente (n8n) y sugerencias pendientes de aprobación.

- ``token_servicio``: credencial de larga duración para un agente automático. Solo se guarda el
  SHA-256 del token (se muestra una única vez al crearlo con la CLI) y un prefijo para
  reconocerlo en los listados. Se revoca, nunca se borra (la auditoría lo referencia).
- ``copiloto_sugerencia``: lo que el agente propone (revisar una válvula, regenerar el plan...).
  Nunca se ejecuta sola: queda **pendiente** hasta que un encargado o admin la aprueba o la
  descarta en la app.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ActualizadoMixin, Base, CreadoMixin, IdMixin

TIPOS_SUGERENCIA = ("revisar_equipo", "revisar_datos", "regenerar_plan", "ajustar_riego", "otro")
ESTADOS_SUGERENCIA = ("pendiente", "aprobada", "descartada")


def _en(valores: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in valores)


class TokenServicio(IdMixin, CreadoMixin, Base):
    __tablename__ = "token_servicio"

    nombre: Mapped[str] = mapped_column(String(60), unique=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Primeros caracteres del token (sin el resto): para reconocerlo en listados y auditoría.
    prefijo: Mapped[str] = mapped_column(String(16))
    activo: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    creado_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), index=True
    )
    ultimo_uso_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revocado_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class CopilotoSugerencia(IdMixin, CreadoMixin, ActualizadoMixin, Base):
    __tablename__ = "copiloto_sugerencia"
    __table_args__ = (
        CheckConstraint(f"tipo IN ({_en(TIPOS_SUGERENCIA)})", name="tipo"),
        CheckConstraint(f"estado IN ({_en(ESTADOS_SUGERENCIA)})", name="estado"),
        Index("ix_copiloto_sugerencia_estado_modulo_id_fecha", "estado", "modulo_id", "fecha"),
        # Una sola pendiente por propuesta: n8n manda varias en paralelo y el agente puede repetirlas.
        # NULLS NOT DISTINCT (PostgreSQL 15+): dos NULL en turno o alerta cuentan como iguales.
        Index("uq_copiloto_sugerencia_pendiente", "modulo_id", "fecha", "tipo", "turno_id", "alerta_codigo",
              func.lower(text("titulo")), unique=True, postgresql_nulls_not_distinct=True,
              postgresql_where=text("estado = 'pendiente'")),
    )

    modulo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("modulo.id"), index=True)
    # Día al que se refiere (no el día en que se creó).
    fecha: Mapped[dt.date] = mapped_column(Date)
    turno_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("turno.id"), index=True)
    tipo: Mapped[str] = mapped_column(String(30))
    # Código de la alerta del motor que la originó (p. ej. ``riego_sin_respuesta``), si la hubo.
    alerta_codigo: Mapped[str | None] = mapped_column(String(40))
    titulo: Mapped[str] = mapped_column(String(160))
    detalle: Mapped[str | None] = mapped_column(Text)
    estado: Mapped[str] = mapped_column(String(20), server_default=text("'pendiente'"), default="pendiente")
    token_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("token_servicio.id", ondelete="SET NULL"), index=True
    )
    resuelto_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id", ondelete="SET NULL"), index=True
    )
    resuelto_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    comentario_resolucion: Mapped[str | None] = mapped_column(Text)
