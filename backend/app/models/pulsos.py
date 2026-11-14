"""Parámetros del riego por pulsos de cada módulo (lo que antes vivía en la planilla Excel)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Boolean, Double, ForeignKey, SmallInteger, String, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import ActualizadoMixin, Base, CreadoMixin, IdMixin


class ParametrosPulsos(IdMixin, CreadoMixin, ActualizadoMixin, Base):
    """Una fila por módulo. Con ``activo`` el cronograma reparte los m³/ha del modelo en pulsos."""

    __tablename__ = "parametros_pulsos"

    modulo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("modulo.id"), unique=True)
    activo: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    # Suelo (fracciones de volumen: 0,14 = 14 %).
    textura_suelo: Mapped[str] = mapped_column(String(30))
    capacidad_campo: Mapped[float] = mapped_column(Double)
    punto_marchitez: Mapped[float] = mapped_column(Double)
    agotamiento_maximo: Mapped[float] = mapped_column(Double)
    infiltracion_basica_mmh: Mapped[float] = mapped_column(Double)
    ancho_humedo_m: Mapped[float] = mapped_column(Double)
    profundidad_raices_m: Mapped[float] = mapped_column(Double)
    diametro_bulbo_m: Mapped[float | None] = mapped_column(Double)  # vacío = distancia entre goteros
    # Sistema de riego.
    distancia_hileras_m: Mapped[float] = mapped_column(Double)
    distancia_plantas_m: Mapped[float] = mapped_column(Double)
    mangueras_por_hilera: Mapped[int] = mapped_column(SmallInteger)
    separacion_mangueras_m: Mapped[float] = mapped_column(Double)
    distancia_goteros_m: Mapped[float] = mapped_column(Double)
    caudal_gotero_lh: Mapped[float] = mapped_column(Double)
    reposo_min_por_hora: Mapped[float] = mapped_column(Double)
    eficiencia_aplicacion: Mapped[float] = mapped_column(Double)
    # Fenología y ventana de riego.
    fase_fenologica: Mapped[str] = mapped_column(String(40))
    agotamiento_por_fase: Mapped[dict[str, Any]] = mapped_column(JSONB)
    agotamiento_automatico: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    umbral_etr_1: Mapped[float] = mapped_column(Double)
    umbral_etr_2: Mapped[float] = mapped_column(Double)
    modo_ventana: Mapped[str] = mapped_column(String(30))
    curvas: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ajustar_pulso_al_total: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)
    actualizado_por: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("usuario.id"), index=True)
