"""Consultas de reportes (F5): agua aplicada vs propuesta, KPIs y exportaciones."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Cronograma,
    CronogramaVersion,
    Modulo,
    ModeloVersion,
    PrediccionEntrada,
)


def cronogramas_rango(db: Session, modulo_id: int, desde: dt.date, hasta: dt.date) -> list[Cronograma]:
    return list(db.scalars(
        select(Cronograma)
        .where(Cronograma.modulo_id == modulo_id, Cronograma.fecha >= desde, Cronograma.fecha <= hasta)
        .order_by(Cronograma.fecha)
    ))


def cronogramas_todos_modulos(db: Session, desde: dt.date, hasta: dt.date) -> list[Cronograma]:
    return list(db.scalars(
        select(Cronograma).where(Cronograma.fecha >= desde, Cronograma.fecha <= hasta)
        .order_by(Cronograma.modulo_id, Cronograma.fecha)
    ))


def versiones_de(db: Session, cronograma_ids: Sequence[int]) -> list[CronogramaVersion]:
    """Todas las versiones (con turnos y ciclos) de los cronogramas dados, por número."""
    if not cronograma_ids:
        return []
    return list(db.scalars(
        select(CronogramaVersion)
        .where(CronogramaVersion.cronograma_id.in_(list(cronograma_ids)))
        .options(selectinload(CronogramaVersion.turnos), selectinload(CronogramaVersion.ciclos))
        .order_by(CronogramaVersion.cronograma_id, CronogramaVersion.numero)
    ))


def fotos(db: Session, generacion_ids: Sequence[int]) -> dict[tuple[int, dt.date, int], PrediccionEntrada]:
    """``(generacion_id, fecha, turno_id) -> PrediccionEntrada``."""
    ids = [i for i in set(generacion_ids) if i]
    if not ids:
        return {}
    filas = db.scalars(select(PrediccionEntrada).where(PrediccionEntrada.generacion_id.in_(ids)))
    return {(f.generacion_id, f.fecha, f.turno_id): f for f in filas}


def modulos(db: Session) -> dict[int, Modulo]:
    return {m.id: m for m in db.scalars(select(Modulo))}


def nombres_modelo(db: Session) -> dict[int, str]:
    return dict(db.execute(select(ModeloVersion.id, ModeloVersion.version)).all())
