"""Cronogramas, versiones inmutables, foto de entradas del modelo y línea de tiempo."""

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
    SmallInteger,
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

from app.db.base import ActualizadoMixin, Base, CreadoMixin, IdMixin
from app.models.enums import (
    ESTADO_CRONOGRAMA,
    ORIGEN_RIEGO_D1,
    ORIGEN_VERSION,
    TIPO_EVENTO_CRONOGRAMA,
    TIPO_GENERACION,
    EstadoCronograma,
    OrigenRiegoD1,
    OrigenVersion,
    TipoEventoCronograma,
    TipoGeneracion,
)


class MotivoCorreccion(IdMixin, CreadoMixin, Base):
    __tablename__ = "motivo_correccion"

    codigo: Mapped[str] = mapped_column(String(40), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    orden: Mapped[int] = mapped_column(SmallInteger)
    activo: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)


class ModeloVersion(IdMixin, Base):
    """Modelo ``.joblib`` registrado al iniciar (``ON CONFLICT DO NOTHING``)."""

    __tablename__ = "modelo_version"

    version: Mapped[str] = mapped_column(String(40), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    # "metadata" está reservado en SQLAlchemy: el atributo se llama metadatos.
    metadatos: Mapped[dict[str, Any] | None] = mapped_column("metadata", JSONB)
    ruta: Mapped[str | None] = mapped_column(String(500))
    registrado_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Generacion(IdMixin, CreadoMixin, Base):
    """Agrupa lo creado en un "Generar" o "Regenerar"."""

    __tablename__ = "generacion"

    modulo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("modulo.id"), index=True)
    fecha_inicio: Mapped[dt.date] = mapped_column(Date)
    dias: Mapped[int] = mapped_column(SmallInteger)
    tipo: Mapped[TipoGeneracion] = mapped_column(TIPO_GENERACION)
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuario.id"), index=True)
    modelo_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("modelo_version.id"), index=True
    )
    frescura: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    resultado_por_dia: Mapped[Any] = mapped_column(JSONB)
    duracion_ms: Mapped[int | None] = mapped_column(Integer)


class Cronograma(IdMixin, CreadoMixin, ActualizadoMixin, Base):
    """Un cronograma por módulo y fecha."""

    __tablename__ = "cronograma"
    __table_args__ = (UniqueConstraint("modulo_id", "fecha"), Index("ix_cronograma_estado", "estado"))

    modulo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("modulo.id"))
    fecha: Mapped[dt.date] = mapped_column(Date)
    estado: Mapped[EstadoCronograma] = mapped_column(
        ESTADO_CRONOGRAMA, server_default=EstadoCronograma.borrador.value, default=EstadoCronograma.borrador
    )
    version_publicada_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cronograma_version.id", use_alter=True), index=True
    )
    # Borrador (estado Borrador) o "borrador de cambios" de un publicado; el programador no lo ve.
    borrador_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cronograma_version.id", use_alter=True), index=True
    )
    visto_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cronograma_version.id", use_alter=True), index=True
    )
    visto_programador_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    visto_programador_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id"), index=True
    )
    num_publicaciones: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    correccion_solicitada_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    correccion_solicitada_por: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("usuario.id"), index=True
    )
    correccion_solicitada_motivo: Mapped[str | None] = mapped_column(Text)
    # Bloqueo optimista para las ediciones concurrentes.
    lock_version: Mapped[int] = mapped_column(Integer, server_default=text("1"), default=1)


class CronogramaVersion(IdMixin, CreadoMixin, Base):
    """Versión inmutable: solo se puede fijar ``publicada_at/publicada_por`` una vez."""

    __tablename__ = "cronograma_version"
    __table_args__ = (UniqueConstraint("cronograma_id", "numero"),)

    cronograma_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cronograma.id"))
    numero: Mapped[int] = mapped_column(Integer)
    origen: Mapped[OrigenVersion] = mapped_column(ORIGEN_VERSION)
    generacion_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("generacion.id"), index=True
    )
    modelo_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("modelo_version.id"), index=True
    )
    basada_en_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cronograma_version.id"), index=True
    )
    motivo_codigo: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("motivo_correccion.codigo"), index=True
    )
    motivo_comentario: Mapped[str | None] = mapped_column(Text)
    preliminar: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    datos_incompletos: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    creado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuario.id"), index=True)
    publicada_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    publicada_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuario.id"), index=True)

    turnos: Mapped[list[CronogramaTurno]] = relationship(back_populates="version")
    ciclos: Mapped[list[CronogramaCiclo]] = relationship(
        back_populates="version", order_by="(CronogramaCiclo.turno_id, CronogramaCiclo.ciclo)"
    )


class CronogramaTurno(IdMixin, CreadoMixin, Base):
    __tablename__ = "cronograma_turno"
    __table_args__ = (UniqueConstraint("version_id", "turno_id"),)

    version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cronograma_version.id"))
    turno_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("turno.id"), index=True)
    n_ciclos: Mapped[int] = mapped_column(SmallInteger)
    n_ciclos_modelo: Mapped[int | None] = mapped_column(SmallInteger)
    # Minutos por m3/ha (sin redondear, de plan.factor_duracion); duración = m3/ha × factor.
    factor_min_por_m3ha: Mapped[float | None] = mapped_column(Double)
    area_ha: Mapped[float] = mapped_column(Double)
    caudal_m3h: Mapped[float | None] = mapped_column(Double)

    version: Mapped[CronogramaVersion] = relationship(back_populates="turnos")


class CronogramaCiclo(IdMixin, CreadoMixin, Base):
    """Ciclo de una versión. Minutos desde las 00:00 de la fecha (inicio puede ser ≥ 1440)."""

    __tablename__ = "cronograma_ciclo"
    __table_args__ = (UniqueConstraint("version_id", "turno_id", "ciclo"),)

    version_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cronograma_version.id"))
    turno_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("turno.id"), index=True)
    ciclo: Mapped[int] = mapped_column(SmallInteger)
    riego_m3ha: Mapped[float] = mapped_column(Double)
    riego_m3: Mapped[float] = mapped_column(Double)
    duracion_min: Mapped[float] = mapped_column(Double)
    inicio_min: Mapped[float] = mapped_column(Double)
    fin_min: Mapped[float] = mapped_column(Double)
    hora_inicio: Mapped[str] = mapped_column(String(5))
    hora_fin: Mapped[str] = mapped_column(String(5))
    fin_dia_siguiente: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    m3ha_p10: Mapped[float | None] = mapped_column(Double)
    m3ha_p90: Mapped[float | None] = mapped_column(Double)
    duracion_p10: Mapped[float | None] = mapped_column(Double)
    duracion_p90: Mapped[float | None] = mapped_column(Double)
    # Rango probable del inicio (p10–p90), en minutos desde las 00:00.
    inicio_desde_min: Mapped[float | None] = mapped_column(Double)
    inicio_hasta_min: Mapped[float | None] = mapped_column(Double)
    ciclo_modelo: Mapped[int | None] = mapped_column(SmallInteger)
    duracion_manual: Mapped[bool] = mapped_column(Boolean, server_default=false(), default=False)
    campos_editados: Mapped[list[str]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )

    version: Mapped[CronogramaVersion] = relationship(back_populates="ciclos")


class PrediccionEntrada(IdMixin, CreadoMixin, Base):
    """"Foto" de las entradas del modelo por generación, fecha y turno (inmutable)."""

    __tablename__ = "prediccion_entrada"
    __table_args__ = (UniqueConstraint("generacion_id", "fecha", "turno_id"),)

    generacion_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("generacion.id"))
    fecha: Mapped[dt.date] = mapped_column(Date)
    turno_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("turno.id"), index=True)
    modelo_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("modelo_version.id"), index=True
    )
    features_turno: Mapped[dict[str, Any]] = mapped_column(JSONB)
    features_ciclo: Mapped[Any] = mapped_column(JSONB)
    # Salida del modelo forzando n = 1..5 (para cambiar el n° de ciclos al editar).
    alternativas_n: Mapped[Any] = mapped_column(JSONB)
    origen_riego_d1: Mapped[OrigenRiegoD1] = mapped_column(ORIGEN_RIEGO_D1)
    fuentes_hasta: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class CronogramaEvento(IdMixin, Base):
    """Línea de tiempo del cronograma (solo inserción)."""

    __tablename__ = "cronograma_evento"
    __table_args__ = (Index("ix_cronograma_evento_cronograma_id_ocurrido_at", "cronograma_id", "ocurrido_at"),)

    cronograma_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("cronograma.id"))
    version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cronograma_version.id"), index=True
    )
    tipo: Mapped[TipoEventoCronograma] = mapped_column(TIPO_EVENTO_CRONOGRAMA)
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuario.id"), index=True)
    ocurrido_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    motivo_codigo: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("motivo_correccion.codigo"), index=True
    )
    comentario: Mapped[str | None] = mapped_column(Text)
    detalle: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
