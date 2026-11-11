"""Riego aplicado: un registro versionado por turno × día y sus ciclos; cargas de Excel."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreadoMixin, IdMixin
from app.models.enums import (
    ESTADO_CARGA,
    ESTADO_RIEGO,
    ORIGEN_RIEGO,
    RESULTADO_CARGA,
    EstadoCarga,
    EstadoRiego,
    OrigenRiego,
    ResultadoCarga,
)


class RiegoRegistro(IdMixin, CreadoMixin, Base):
    """Versión del riego de un turno-día. Editar crea otra versión; nunca se borra."""

    __tablename__ = "riego_registro"
    __table_args__ = (
        UniqueConstraint("turno_id", "fecha", "version"),
        # Un solo registro vigente por turno-día.
        Index(
            "uq_riego_registro_turno_id_fecha_vigente",
            "turno_id",
            "fecha",
            unique=True,
            postgresql_where=text("vigente"),
        ),
        Index("ix_riego_registro_modulo_id_fecha", "modulo_id", "fecha"),
    )

    modulo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("modulo.id"))
    turno_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("turno.id"))
    fecha: Mapped[dt.date] = mapped_column(Date)
    version: Mapped[int] = mapped_column(Integer)
    vigente: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    estado: Mapped[EstadoRiego] = mapped_column(ESTADO_RIEGO)
    origen: Mapped[OrigenRiego] = mapped_column(ORIGEN_RIEGO)
    # Registro con 0 ciclos = "no se regó" (cuenta como dato).
    sin_riego: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    contenido_sha256: Mapped[str] = mapped_column(String(64))
    cronograma_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cronograma_version.id"), index=True
    )
    carga_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("carga_riego.id"), index=True)
    basado_en_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("riego_registro.id"), index=True
    )
    motivo: Mapped[str | None] = mapped_column(String(255))
    comentario: Mapped[str | None] = mapped_column(Text)
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuario.id"), index=True)

    ciclos: Mapped[list[RiegoCiclo]] = relationship(
        back_populates="registro", order_by="RiegoCiclo.inicio_min"
    )


class RiegoCiclo(IdMixin, CreadoMixin, Base):
    """Ciclo de un registro (inmutable). Minutos desde las 00:00 de la fecha del registro."""

    __tablename__ = "riego_ciclo"
    __table_args__ = (UniqueConstraint("registro_id", "inicio_min"),)

    registro_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("riego_registro.id"))
    inicio_min: Mapped[float] = mapped_column(Double)
    fin_min: Mapped[float] = mapped_column(Double)  # puede superar 1440
    duracion_min: Mapped[float] = mapped_column(Double)
    riego_m3: Mapped[float | None] = mapped_column(Double)
    riego_m3ha: Mapped[float | None] = mapped_column(Double)
    area_ha: Mapped[float | None] = mapped_column(Double)
    valvula: Mapped[str | None] = mapped_column(String(20))
    hora_inicio: Mapped[str] = mapped_column(String(5))  # HH:MM
    hora_fin: Mapped[str] = mapped_column(String(5))
    fin_dia_siguiente: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)

    registro: Mapped[RiegoRegistro] = relationship(back_populates="ciclos")


class CargaRiego(IdMixin, Base):
    """Excel de riego subido: vista previa y confirmación (vence a las 24 h)."""

    __tablename__ = "carga_riego"

    modulo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("modulo.id"), index=True)
    archivo_nombre: Mapped[str] = mapped_column(String(255))  # saneado
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    tamano_bytes: Mapped[int] = mapped_column(BigInteger)
    subido_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuario.id"), index=True)
    subido_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    estado: Mapped[EstadoCarga] = mapped_column(
        ESTADO_CARGA, server_default=EstadoCarga.previsualizada.value, default=EstadoCarga.previsualizada
    )
    resumen: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    confirmado_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id"), index=True
    )
    confirmado_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class CargaRiegoTurnoDia(IdMixin, CreadoMixin, Base):
    """Resultado de la comparación de un turno-día del Excel con el registro vigente."""

    __tablename__ = "carga_riego_turno_dia"
    __table_args__ = (
        Index("ix_carga_riego_turno_dia_carga_id_fecha_turno_id", "carga_id", "fecha", "turno_id"),
    )

    carga_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("carga_riego.id", ondelete="CASCADE"))
    fecha: Mapped[dt.date] = mapped_column(Date)
    # NULL si el turno del archivo no existe (resultado = error); se guarda el texto original.
    turno_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("turno.id"), index=True)
    turno_codigo: Mapped[str | None] = mapped_column(String(20))
    resultado: Mapped[ResultadoCarga] = mapped_column(RESULTADO_CARGA)
    vigente_id_comparado: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("riego_registro.id"), index=True
    )
    ciclos: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    mensajes: Mapped[list[str] | None] = mapped_column(JSONB)
    aplicar: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
