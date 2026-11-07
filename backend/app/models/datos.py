"""Datos de campo: corridas de ingesta, crudo de las APIs, lecturas limpias y ambiente diario.

Las lecturas de sensores usan ``timestamp`` **sin zona** en hora local de Lima (igual que
``riego_ml``); los instantes de sistema usan ``timestamptz``.
"""

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ActualizadoMixin, Base, CreadoMixin, IdMixin
from app.models.enums import (
    DISPARO_INGESTA,
    ESTADO_INGESTA,
    ORIGEN_METEO,
    DisparoIngesta,
    EstadoIngesta,
    OrigenMeteo,
)

# Columnas de riego_ml.dataset.unir.columnas_ambiente() en minúsculas (38). Un test verifica
# que coincidan con riego_ml; F2 las mapea al nombre original al armar el Historial.
COLUMNAS_AMBIENTE = (
    "t_media", "t_max", "t_min", "hr_media", "hr_min", "hr_max", "eto_mm",
    "dpv_media", "dpv_max", "viento_media", "lluvia_mm", "rad_max", "rad_media",
    "horas_t30", "meteo_lecturas",
    "hum_15cm_media", "hum_30cm_media", "hum_45cm_media", "hum_60cm_media",
    "hum_75cm_media", "hum_90cm_media", "hum_zona_radicular_media", "hum_linea_estres_media",
    "hum_15cm_cierre", "hum_30cm_cierre", "hum_45cm_cierre", "hum_60cm_cierre",
    "hum_75cm_cierre", "hum_90cm_cierre", "hum_zona_radicular_cierre", "hum_linea_estres_cierre",
    "hum_45cm_rango", "hum_60cm_rango", "suelo_horas",
    "mds_contraccion_um", "crecimiento_tronco_um", "estres_planta_ps",
    "ndvi_medio",
)


def _corrida_fk() -> Mapped[int | None]:
    return mapped_column(BigInteger, ForeignKey("ingesta_corrida.id", ondelete="SET NULL"), index=True)


class IngestaCorrida(IdMixin, CreadoMixin, Base):
    __tablename__ = "ingesta_corrida"
    __table_args__ = (
        # Exclusión entre procesos de las corridas programadas (las manuales tienen fecha NULL).
        UniqueConstraint("fuente", "fecha_programada"),
        Index("ix_ingesta_corrida_fuente_inicio_at", "fuente", "inicio_at"),
    )

    fuente: Mapped[str] = mapped_column(String(40))
    disparo: Mapped[DisparoIngesta] = mapped_column(DISPARO_INGESTA)
    usuario_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuario.id"), index=True)
    fecha_programada: Mapped[dt.date | None] = mapped_column(Date)
    desde: Mapped[dt.date | None] = mapped_column(Date)
    hasta: Mapped[dt.date | None] = mapped_column(Date)
    inicio_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    fin_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    duracion_ms: Mapped[int | None] = mapped_column(Integer)
    estado: Mapped[EstadoIngesta] = mapped_column(
        ESTADO_INGESTA, server_default=EstadoIngesta.en_curso.value, default=EstadoIngesta.en_curso
    )
    filas_nuevas: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    filas_actualizadas: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    filas_omitidas: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    conflictos: Mapped[int] = mapped_column(Integer, server_default=text("0"), default=0)
    # [{tipo, status_code, endpoint sin query, mensaje redactado}]
    errores: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"), default=list
    )


class IngestaCrudo(IdMixin, CreadoMixin, Base):
    """Payload de una llamada a API tal cual llegó; ``parametros`` sin claves."""

    __tablename__ = "ingesta_crudo"

    corrida_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("ingesta_corrida.id", ondelete="CASCADE"), index=True
    )
    endpoint: Mapped[str] = mapped_column(String(255))
    parametros: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    payload: Mapped[Any] = mapped_column(JSONB)


class MeteoLectura(IdMixin, CreadoMixin, ActualizadoMixin, Base):
    """Lectura de 30 min (unidades de ``riego_ml.sources.meteo``)."""

    __tablename__ = "meteo_lectura"
    __table_args__ = (UniqueConstraint("fundo_id", "fecha_hora"),)

    fundo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fundo.id"))
    # Hora local de Lima del fin del intervalo (sin zona).
    fecha_hora: Mapped[dt.datetime] = mapped_column(DateTime(timezone=False))
    temp: Mapped[float | None] = mapped_column(Double)
    temp_max: Mapped[float | None] = mapped_column(Double)
    temp_min: Mapped[float | None] = mapped_column(Double)
    hr: Mapped[float | None] = mapped_column(Double)
    hr_max: Mapped[float | None] = mapped_column(Double)
    rad: Mapped[float | None] = mapped_column(Double)
    eto: Mapped[float | None] = mapped_column(Double)
    dpv: Mapped[float | None] = mapped_column(Double)
    viento: Mapped[float | None] = mapped_column(Double)
    lluvia: Mapped[float | None] = mapped_column(Double)
    origen: Mapped[OrigenMeteo] = mapped_column(ORIGEN_METEO)
    corrida_id: Mapped[int | None] = _corrida_fk()


class PhytechSueloHorario(IdMixin, CreadoMixin, ActualizadoMixin, Base):
    """Salida horaria de ``limpiar_suelo``."""

    __tablename__ = "phytech_suelo_horario"
    __table_args__ = (UniqueConstraint("project_id", "fecha_hora"),)

    fundo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fundo.id"), index=True)
    plot_id: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[int] = mapped_column(Integer)
    fecha_hora: Mapped[dt.datetime] = mapped_column(DateTime(timezone=False))
    hay_dato: Mapped[bool] = mapped_column(Boolean)
    hum_15cm: Mapped[float | None] = mapped_column(Double)
    hum_30cm: Mapped[float | None] = mapped_column(Double)
    hum_45cm: Mapped[float | None] = mapped_column(Double)
    hum_60cm: Mapped[float | None] = mapped_column(Double)
    hum_75cm: Mapped[float | None] = mapped_column(Double)
    hum_90cm: Mapped[float | None] = mapped_column(Double)
    temp_15cm: Mapped[float | None] = mapped_column(Double)
    temp_30cm: Mapped[float | None] = mapped_column(Double)
    temp_60cm: Mapped[float | None] = mapped_column(Double)
    temp_90cm: Mapped[float | None] = mapped_column(Double)
    hum_zona_radicular: Mapped[float | None] = mapped_column(Double)
    hum_saturacion: Mapped[float | None] = mapped_column(Double)
    hum_linea_estres: Mapped[float | None] = mapped_column(Double)
    hum_zona_radicular_norm_pct: Mapped[float | None] = mapped_column(Double)
    corrida_id: Mapped[int | None] = _corrida_fk()


class PhytechPlantaDiario(IdMixin, CreadoMixin, ActualizadoMixin, Base):
    __tablename__ = "phytech_planta_diario"
    __table_args__ = (UniqueConstraint("project_id", "fecha"),)

    fundo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fundo.id"), index=True)
    plot_id: Mapped[int] = mapped_column(Integer)
    project_id: Mapped[int] = mapped_column(Integer)
    fecha: Mapped[dt.date] = mapped_column(Date)
    mds_contraccion_um: Mapped[float | None] = mapped_column(Double)
    crecimiento_tronco_um: Mapped[float | None] = mapped_column(Double)
    estres_planta_ps: Mapped[float | None] = mapped_column(Double)
    tamano_fruto_mm: Mapped[float | None] = mapped_column(Double)
    crecimiento_fruto_mm: Mapped[float | None] = mapped_column(Double)
    et_mm: Mapped[float | None] = mapped_column(Double)
    lluvia_mm: Mapped[float | None] = mapped_column(Double)
    corrida_id: Mapped[int | None] = _corrida_fk()


class NdviImagen(IdMixin, CreadoMixin, Base):
    __tablename__ = "ndvi_imagen"

    fundo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fundo.id"), index=True)
    image_id: Mapped[str] = mapped_column(String(64), unique=True)
    area_id: Mapped[int] = mapped_column(Integer)
    plot_id: Mapped[int] = mapped_column(Integer)
    fecha: Mapped[dt.date] = mapped_column(Date, index=True)
    no_vegetation: Mapped[bool | None] = mapped_column(Boolean)
    clases: Mapped[Any] = mapped_column(JSONB)
    ndvi_medio: Mapped[float | None] = mapped_column(Double)
    corrida_id: Mapped[int | None] = _corrida_fk()


class PronosticoClima(IdMixin, CreadoMixin, Base):
    """Pronóstico de Phytech: una captura por día (sin historia en la API)."""

    __tablename__ = "pronostico_clima"
    __table_args__ = (UniqueConstraint("project_id", "capturado_fecha", "fecha"),)

    fundo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fundo.id"), index=True)
    project_id: Mapped[int] = mapped_column(Integer)
    capturado_fecha: Mapped[dt.date] = mapped_column(Date)
    fecha: Mapped[dt.date] = mapped_column(Date)
    t_max: Mapped[float | None] = mapped_column(Double)
    eto_mm: Mapped[float | None] = mapped_column(Double)
    etc_mm: Mapped[float | None] = mapped_column(Double)
    humedad: Mapped[float | None] = mapped_column(Double)
    corrida_id: Mapped[int | None] = _corrida_fk()


class AmbienteDiario(IdMixin, CreadoMixin, ActualizadoMixin, Base):
    """Tabla derivada (fundo × día cerrado) con las columnas de ``columnas_ambiente()``."""

    __tablename__ = "ambiente_diario"
    __table_args__ = (UniqueConstraint("fundo_id", "fecha"),)

    fundo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fundo.id"))
    fecha: Mapped[dt.date] = mapped_column(Date)

    t_media: Mapped[float | None] = mapped_column(Double)
    t_max: Mapped[float | None] = mapped_column(Double)
    t_min: Mapped[float | None] = mapped_column(Double)
    hr_media: Mapped[float | None] = mapped_column(Double)
    hr_min: Mapped[float | None] = mapped_column(Double)
    hr_max: Mapped[float | None] = mapped_column(Double)
    eto_mm: Mapped[float | None] = mapped_column(Double)
    dpv_media: Mapped[float | None] = mapped_column(Double)
    dpv_max: Mapped[float | None] = mapped_column(Double)
    viento_media: Mapped[float | None] = mapped_column(Double)
    lluvia_mm: Mapped[float | None] = mapped_column(Double)
    rad_max: Mapped[float | None] = mapped_column(Double)
    rad_media: Mapped[float | None] = mapped_column(Double)
    horas_t30: Mapped[float | None] = mapped_column(Double)
    meteo_lecturas: Mapped[float | None] = mapped_column(Double)
    hum_15cm_media: Mapped[float | None] = mapped_column(Double)
    hum_30cm_media: Mapped[float | None] = mapped_column(Double)
    hum_45cm_media: Mapped[float | None] = mapped_column(Double)
    hum_60cm_media: Mapped[float | None] = mapped_column(Double)
    hum_75cm_media: Mapped[float | None] = mapped_column(Double)
    hum_90cm_media: Mapped[float | None] = mapped_column(Double)
    hum_zona_radicular_media: Mapped[float | None] = mapped_column(Double)
    hum_linea_estres_media: Mapped[float | None] = mapped_column(Double)
    hum_15cm_cierre: Mapped[float | None] = mapped_column(Double)
    hum_30cm_cierre: Mapped[float | None] = mapped_column(Double)
    hum_45cm_cierre: Mapped[float | None] = mapped_column(Double)
    hum_60cm_cierre: Mapped[float | None] = mapped_column(Double)
    hum_75cm_cierre: Mapped[float | None] = mapped_column(Double)
    hum_90cm_cierre: Mapped[float | None] = mapped_column(Double)
    hum_zona_radicular_cierre: Mapped[float | None] = mapped_column(Double)
    hum_linea_estres_cierre: Mapped[float | None] = mapped_column(Double)
    hum_45cm_rango: Mapped[float | None] = mapped_column(Double)
    hum_60cm_rango: Mapped[float | None] = mapped_column(Double)
    suelo_horas: Mapped[float | None] = mapped_column(Double)
    mds_contraccion_um: Mapped[float | None] = mapped_column(Double)
    crecimiento_tronco_um: Mapped[float | None] = mapped_column(Double)
    estres_planta_ps: Mapped[float | None] = mapped_column(Double)
    ndvi_medio: Mapped[float | None] = mapped_column(Double)

    # 0/1 como en riego_ml
    tiene_meteo: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
    tiene_suelo: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
    tiene_planta: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"), default=0)
