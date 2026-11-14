"""Consultas del riego por pulsos: parámetros del módulo y plan original del modelo."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Cronograma, CronogramaVersion, Generacion, ParametrosPulsos, PrediccionEntrada


def parametros(db: Session, modulo_id: int, *, bloquear: bool = False) -> ParametrosPulsos | None:
    consulta = select(ParametrosPulsos).where(ParametrosPulsos.modulo_id == modulo_id)
    if bloquear:
        consulta = consulta.with_for_update()
    return db.scalar(consulta)


def fechas_cronograma_pulsos(db: Session, modulo_id: int, hasta: dt.date) -> set[dt.date]:
    """Fechas ``< hasta`` cuyo cronograma vigente tiene una versión de referencia (publicada; si no
    hay, el borrador) calculada por pulsos."""
    version = func.coalesce(Cronograma.version_publicada_id, Cronograma.borrador_version_id)
    return set(db.scalars(
        select(Cronograma.fecha)
        .join(CronogramaVersion, CronogramaVersion.id == version)
        .where(Cronograma.modulo_id == modulo_id, Cronograma.fecha < hasta, Cronograma.anulado_at.is_(None),
               CronogramaVersion.calculo_pulsos.is_not(None))
    ))


def versiones_con_pulsos(db: Session, ids: Iterable[int | None]) -> set[int]:
    unicos = {i for i in ids if i is not None}
    if not unicos:
        return set()
    return set(db.scalars(select(CronogramaVersion.id).where(
        CronogramaVersion.id.in_(unicos), CronogramaVersion.calculo_pulsos.is_not(None))))


def planes_modelo(db: Session, modulo_id: int, fechas: Iterable[dt.date]) -> dict[tuple[dt.date, int], Any]:
    """``(fecha, turno_id) -> ciclos del modelo`` de la última generación de cada fecha."""
    fechas = set(fechas)
    if not fechas:
        return {}
    ultima = (
        select(func.max(PrediccionEntrada.id).label("id"))
        .join(Generacion, Generacion.id == PrediccionEntrada.generacion_id)
        .where(Generacion.modulo_id == modulo_id, PrediccionEntrada.fecha.in_(fechas),
               PrediccionEntrada.plan_modelo.is_not(None))
        .group_by(PrediccionEntrada.fecha, PrediccionEntrada.turno_id)
    )
    filas = db.execute(
        select(PrediccionEntrada.fecha, PrediccionEntrada.turno_id, PrediccionEntrada.plan_modelo)
        .where(PrediccionEntrada.id.in_(ultima))
    )
    return {(f.fecha, f.turno_id): f.plan_modelo for f in filas}
