"""Organización: empresa › fundo › módulo › turno › lote (datos semilla)."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Double, ForeignKey, SmallInteger, String, UniqueConstraint, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, CreadoMixin, IdMixin


class Empresa(IdMixin, CreadoMixin, Base):
    __tablename__ = "empresa"

    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    activo: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)

    fundos: Mapped[list[Fundo]] = relationship(back_populates="empresa")


class Fundo(IdMixin, CreadoMixin, Base):
    __tablename__ = "fundo"

    empresa_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("empresa.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(20), unique=True)
    # Unicode NFC (ENSUEÑO con Ñ precompuesta): debe coincidir con el texto de riego_ml.
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    zona: Mapped[str | None] = mapped_column(String(60))
    activo: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)

    empresa: Mapped[Empresa] = relationship(back_populates="fundos")
    modulos: Mapped[list[Modulo]] = relationship(back_populates="fundo", order_by="Modulo.codigo")


class Modulo(IdMixin, CreadoMixin, Base):
    __tablename__ = "modulo"

    fundo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("fundo.id"), index=True)
    codigo: Mapped[str] = mapped_column(String(30), unique=True)
    nombre: Mapped[str] = mapped_column(String(120))
    area_ha: Mapped[float] = mapped_column(Double)
    cultivo: Mapped[str | None] = mapped_column(String(60))
    variedad: Mapped[str | None] = mapped_column(String(60))
    campana: Mapped[str | None] = mapped_column(String(20))
    activo: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)

    fundo: Mapped[Fundo] = relationship(back_populates="modulos")
    turnos: Mapped[list[Turno]] = relationship(back_populates="modulo", order_by="Turno.orden")


class Turno(IdMixin, CreadoMixin, Base):
    __tablename__ = "turno"
    __table_args__ = (UniqueConstraint("modulo_id", "codigo"),)

    # El índice de uq(modulo_id, codigo) cubre la clave foránea.
    modulo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("modulo.id"))
    codigo: Mapped[str] = mapped_column(String(10))
    orden: Mapped[int] = mapped_column(SmallInteger)
    area_ha: Mapped[float] = mapped_column(Double)
    valvula_controlador: Mapped[str] = mapped_column(String(20), unique=True)
    valvula_siga: Mapped[str | None] = mapped_column(String(20))
    activo: Mapped[bool] = mapped_column(Boolean, server_default=true(), default=True)

    modulo: Mapped[Modulo] = relationship(back_populates="turnos")
    lotes: Mapped[list[Lote]] = relationship(back_populates="turno", order_by="Lote.codigo")


class Lote(IdMixin, CreadoMixin, Base):
    __tablename__ = "lote"
    __table_args__ = (UniqueConstraint("turno_id", "codigo", "campana"),)

    turno_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("turno.id"))
    codigo: Mapped[str] = mapped_column(String(10))
    area_ha: Mapped[float] = mapped_column(Double)
    campana: Mapped[str] = mapped_column(String(20))

    turno: Mapped[Turno] = relationship(back_populates="lotes")
