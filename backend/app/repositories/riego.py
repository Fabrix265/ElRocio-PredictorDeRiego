"""Consultas de riego aplicado (``riego_registro`` / ``riego_ciclo``), de las cargas de Excel
(``carga_riego`` / ``carga_riego_turno_dia``) y de los ciclos del cronograma de referencia que el
Historial usa cuando un turno-día no tiene registro (§2.3)."""

from __future__ import annotations

import datetime as dt
import enum
import json
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import Enum, Text, bindparam, cast, func, select, text, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, insert
from sqlalchemy.orm import Session, selectinload

from app.models import (
    CargaRiego,
    CargaRiegoTurnoDia,
    Cronograma,
    CronogramaCiclo,
    RiegoCiclo,
    RiegoRegistro,
    Turno,
    Usuario,
)
from app.repositories import masivo

LOTE_INSERT = 1000  # ids por UPDATE


def bloquear_turno_dia(db: Session, turno_id: int, fecha: dt.date) -> RiegoRegistro | None:
    """Serializa también la primera inserción (sin fila aún); luego bloquea el vigente.

    F4 toma primero el cronograma, si existe, y después estos candados en orden de turno.
    """
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:clave, 0))"),
               {"clave": f"riego.turno_dia:{turno_id}:{fecha.isoformat()}"})
    return db.scalar(select(RiegoRegistro).where(
        RiegoRegistro.turno_id == turno_id, RiegoRegistro.fecha == fecha, RiegoRegistro.vigente.is_(True),
    ).with_for_update().execution_options(populate_existing=True))


def max_version_turno_dia(db: Session, turno_id: int, fecha: dt.date) -> int:
    return db.scalar(select(func.coalesce(func.max(RiegoRegistro.version), 0)).where(
        RiegoRegistro.turno_id == turno_id, RiegoRegistro.fecha == fecha,
    ))


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
    """``(turno_id, fecha) -> fila(id, version, contenido_sha256, estado, origen, n_ciclos,
    m3_total)`` de los vigentes."""
    ciclos = (
        select(RiegoCiclo.registro_id, func.count().label("n_ciclos"),
               func.coalesce(func.sum(RiegoCiclo.riego_m3), 0.0).label("m3_total"))
        .group_by(RiegoCiclo.registro_id)
        .subquery()
    )
    filas = db.execute(
        select(RiegoRegistro.id, RiegoRegistro.turno_id, RiegoRegistro.fecha, RiegoRegistro.version,
               RiegoRegistro.contenido_sha256, RiegoRegistro.estado, RiegoRegistro.origen,
               func.coalesce(ciclos.c.n_ciclos, 0).label("n_ciclos"),
               func.coalesce(ciclos.c.m3_total, 0.0).label("m3_total"))
        .outerjoin(ciclos, ciclos.c.registro_id == RiegoRegistro.id)
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
        .where(Cronograma.modulo_id == modulo_id, Cronograma.fecha < hasta, Cronograma.anulado_at.is_(None))
        .order_by(Cronograma.fecha, CronogramaCiclo.turno_id, CronogramaCiclo.inicio_min)
    ))


# --- Riego aplicado: listado y versiones (§4 "Riego aplicado") ------------------


def ultima_fecha_vigente(db: Session, modulo_id: int, hasta: dt.date) -> dt.date | None:
    """Último dato hasta la fecha inclusiva; también cuenta provisional y «sin riego»."""
    return db.scalar(select(func.max(RiegoRegistro.fecha)).where(
        RiegoRegistro.modulo_id == modulo_id, RiegoRegistro.vigente.is_(True), RiegoRegistro.fecha <= hasta,
    ))

def versiones_turno_dia(db: Session, turno_id: int, fecha: dt.date) -> list[RiegoRegistro]:
    """Todas las versiones de un turno-día (vigente o no), de la 1 (original) en adelante."""
    return list(db.scalars(
        select(RiegoRegistro)
        .where(RiegoRegistro.turno_id == turno_id, RiegoRegistro.fecha == fecha)
        .options(selectinload(RiegoRegistro.ciclos))
        .order_by(RiegoRegistro.version)
    ))


def usernames(db: Session, ids: Iterable[int | None]) -> dict[int, str]:
    """``usuario_id -> username`` de los IDs dados (sin consultar si no hay ninguno)."""
    unicos = {i for i in ids if i is not None}
    if not unicos:
        return {}
    return dict(db.execute(select(Usuario.id, Usuario.username).where(Usuario.id.in_(unicos))).all())


def bloquear_vigentes(db: Session, modulo_id: int, desde: dt.date, hasta: dt.date) -> dict[tuple[int, dt.date], Any]:
    """Vigentes del módulo con ``desde <= fecha <= hasta`` bloqueados (``FOR UPDATE``) hasta el
    commit: ``(turno_id, fecha) -> fila(id, version, contenido_sha256, estado, origen)``."""
    filas = db.execute(
        select(RiegoRegistro.id, RiegoRegistro.turno_id, RiegoRegistro.fecha, RiegoRegistro.version,
               RiegoRegistro.contenido_sha256, RiegoRegistro.estado, RiegoRegistro.origen)
        .where(RiegoRegistro.modulo_id == modulo_id, RiegoRegistro.vigente.is_(True),
               RiegoRegistro.fecha >= desde, RiegoRegistro.fecha <= hasta)
        .order_by(RiegoRegistro.id)
        .with_for_update()
    )
    return {(f.turno_id, f.fecha): f for f in filas}


# --- Cargas de Excel (§3.5) ---------------------------------------------------------

def carga(db: Session, carga_id: int, *, bloquear: bool = False) -> CargaRiego | None:
    consulta = select(CargaRiego).where(CargaRiego.id == carga_id)
    if bloquear:
        consulta = consulta.with_for_update()
    return db.scalars(consulta).one_or_none()


def insertar_grupos(db: Session, filas: Sequence[dict[str, Any]]) -> None:
    """Inserta los turno-días de una carga en lotes con ``unnest`` (las columnas ``jsonb``
    viajan como texto JSON y se convierten en el SELECT)."""
    if not filas:
        return
    tabla = CargaRiegoTurnoDia.__table__
    columnas = list(filas[0].keys())
    arreglos = []
    for columna in columnas:
        tipo = tabla.c[columna].type
        tipo_arreglo = ARRAY(Text()) if isinstance(tipo, Enum | JSONB) else ARRAY(tipo)
        arreglos.append(cast(bindparam(f"p_{columna}", type_=tipo_arreglo), tipo_arreglo))
    origen = func.unnest(*arreglos).table_valued(*columnas).render_derived(name="u")
    seleccion = select(*[
        cast(origen.c[c], tabla.c[c].type) if isinstance(tabla.c[c].type, Enum | JSONB) else origen.c[c]
        for c in columnas
    ])
    sentencia = insert(tabla).from_select(columnas, seleccion)

    def _valor(columna: str, valor: Any) -> Any:
        if isinstance(tabla.c[columna].type, JSONB):
            return None if valor is None else json.dumps(valor, ensure_ascii=False)
        return valor.value if isinstance(valor, enum.Enum) else valor

    for inicio in range(0, len(filas), masivo.LOTE):
        lote = filas[inicio:inicio + masivo.LOTE]
        db.execute(sentencia, {f"p_{c}": [_valor(c, f.get(c)) for f in lote] for c in columnas})


def grupos_de_carga(db: Session, carga_id: int) -> list[Any]:
    """Turno-días de la carga con el estado y origen del registro vigente comparado."""
    g = CargaRiegoTurnoDia
    return list(db.execute(
        select(g.id, g.fecha, g.turno_id, g.turno_codigo, g.resultado, g.aplicar,
               g.vigente_id_comparado, g.ciclos, g.mensajes,
               RiegoRegistro.estado.label("vigente_estado"), RiegoRegistro.origen.label("vigente_origen"))
        .outerjoin(RiegoRegistro, RiegoRegistro.id == g.vigente_id_comparado)
        .where(g.carga_id == carga_id)
        .order_by(g.fecha, g.turno_codigo, g.id)
    ))


def grupos_por_id(db: Session, carga_id: int, ids: Iterable[int]) -> dict[int, CargaRiegoTurnoDia]:
    lista = list(set(ids))
    encontrados: dict[int, CargaRiegoTurnoDia] = {}
    for inicio in range(0, len(lista), LOTE_INSERT):
        encontrados.update({
            g.id: g for g in db.scalars(
                select(CargaRiegoTurnoDia).where(
                    CargaRiegoTurnoDia.carga_id == carga_id,
                    CargaRiegoTurnoDia.id.in_(lista[inicio:inicio + LOTE_INSERT]),
                )
            )
        })
    return encontrados


def fijar_aplicar(db: Session, carga_id: int, ids: Sequence[int], aplicar: bool) -> None:
    for inicio in range(0, len(ids), LOTE_INSERT):
        db.execute(
            update(CargaRiegoTurnoDia)
            .where(CargaRiegoTurnoDia.carga_id == carga_id,
                   CargaRiegoTurnoDia.id.in_(list(ids[inicio:inicio + LOTE_INSERT])))
            .values(aplicar=aplicar)
            .execution_options(synchronize_session=False)
        )


def grupos_para_confirmar(db: Session, carga_id: int) -> list[CargaRiegoTurnoDia]:
    return list(db.scalars(
        select(CargaRiegoTurnoDia).where(CargaRiegoTurnoDia.carga_id == carga_id)
        .order_by(CargaRiegoTurnoDia.fecha, CargaRiegoTurnoDia.turno_id)
    ))
