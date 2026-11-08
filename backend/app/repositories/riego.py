"""Consultas de riego aplicado (``riego_registro`` / ``riego_ciclo``) y de los ciclos del
cronograma de referencia que el Historial usa cuando un turno-día no tiene registro (§2.3)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.models import (
    Cronograma,
    CronogramaCiclo,
    RiegoCiclo,
    RiegoRegistro,
    Turno,
)
from app.repositories import masivo

LOTE_INSERT = 1000  # ids por UPDATE


def turnos_de_modulo(db: Session, modulo_id: int) -> list[Turno]:
    return list(db.scalars(select(Turno).where(Turno.modulo_id == modulo_id).order_by(Turno.orden, Turno.id)))


def vigentes(
    db: Session, modulo_id: int, *, desde: dt.date | None = None, hasta: dt.date | None = None,
    con_ciclos: bool = True,
) -> list[RiegoRegistro]:
    """Registros vigentes del módulo con ``desde <= fecha < hasta`` (``hasta`` exclusivo)."""
    consulta = select(RiegoRegistro).where(RiegoRegistro.modulo_id == modulo_id, RiegoRegistro.vigente.is_(True))
    if desde is not None:
        consulta = consulta.where(RiegoRegistro.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(RiegoRegistro.fecha < hasta)
    if con_ciclos:
        consulta = consulta.options(selectinload(RiegoRegistro.ciclos))
    return list(db.scalars(consulta.order_by(RiegoRegistro.fecha, RiegoRegistro.turno_id)))


def resumen_vigentes(db: Session, modulo_id: int) -> dict[tuple[int, dt.date], Any]:
    """``(turno_id, fecha) -> fila(id, version, contenido_sha256, estado, origen)`` de los vigentes."""
    filas = db.execute(
        select(RiegoRegistro.id, RiegoRegistro.turno_id, RiegoRegistro.fecha, RiegoRegistro.version,
               RiegoRegistro.contenido_sha256, RiegoRegistro.estado, RiegoRegistro.origen)
        .where(RiegoRegistro.modulo_id == modulo_id, RiegoRegistro.vigente.is_(True))
    )
    return {(f.turno_id, f.fecha): f for f in filas}


def max_versiones(db: Session, modulo_id: int) -> dict[tuple[int, dt.date], int]:
    filas = db.execute(
        select(RiegoRegistro.turno_id, RiegoRegistro.fecha, func.max(RiegoRegistro.version))
        .where(RiegoRegistro.modulo_id == modulo_id)
        .group_by(RiegoRegistro.turno_id, RiegoRegistro.fecha)
    )
    return {(t, f): v for t, f, v in filas}


def dejar_de_ser_vigentes(db: Session, ids: Sequence[int]) -> None:
    """La única modificación permitida sobre un registro (también por trigger)."""
    for inicio in range(0, len(ids), LOTE_INSERT):
        db.execute(
            update(RiegoRegistro)
            .where(RiegoRegistro.id.in_(list(ids[inicio:inicio + LOTE_INSERT])))
            .values(vigente=False)
            .execution_options(synchronize_session="fetch")
        )


def insertar_registros(db: Session, filas: Sequence[dict[str, Any]]) -> dict[tuple[int, dt.date], int]:
    """Inserta registros y devuelve ``(turno_id, fecha) -> id``."""
    ids: dict[tuple[int, dt.date], int] = {}
    if not filas:
        return ids
    tabla = RiegoRegistro.__table__
    columnas = list(filas[0].keys())
    sentencia = masivo.insert_unnest(tabla, columnas).returning(tabla.c.id, tabla.c.turno_id, tabla.c.fecha)
    for inicio in range(0, len(filas), masivo.LOTE):
        lote = filas[inicio:inicio + masivo.LOTE]
        resultado = db.execute(sentencia, masivo.parametros(columnas, lote))
        ids.update({(f.turno_id, f.fecha): f.id for f in resultado})
    return ids


def insertar_ciclos(db: Session, filas: Sequence[dict[str, Any]]) -> None:
    if not filas:
        return
    tabla = RiegoCiclo.__table__
    columnas = list(filas[0].keys())
    sentencia = masivo.insert_unnest(tabla, columnas)
    for inicio in range(0, len(filas), masivo.LOTE):
        db.execute(sentencia, masivo.parametros(columnas, filas[inicio:inicio + masivo.LOTE]))


def ciclos_cronograma_referencia(db: Session, modulo_id: int, hasta: dt.date) -> list[Any]:
    """Ciclos de la versión de referencia (publicada; si no hay, el borrador) de cada cronograma
    del módulo con ``fecha < hasta``: filas ``(fecha, turno_id, inicio_min, fin_min, duracion_min,
    riego_m3, riego_m3ha, hora_inicio, hora_fin, fin_dia_siguiente)``."""
    version = func.coalesce(Cronograma.version_publicada_id, Cronograma.borrador_version_id)
    return list(db.execute(
        select(Cronograma.fecha, CronogramaCiclo.turno_id, CronogramaCiclo.inicio_min,
               CronogramaCiclo.fin_min, CronogramaCiclo.duracion_min, CronogramaCiclo.riego_m3,
               CronogramaCiclo.riego_m3ha, CronogramaCiclo.hora_inicio, CronogramaCiclo.hora_fin,
               CronogramaCiclo.fin_dia_siguiente)
        .join(CronogramaCiclo, CronogramaCiclo.version_id == version)
        .where(Cronograma.modulo_id == modulo_id, Cronograma.fecha < hasta)
        .order_by(Cronograma.fecha, CronogramaCiclo.turno_id, CronogramaCiclo.inicio_min)
    ))
