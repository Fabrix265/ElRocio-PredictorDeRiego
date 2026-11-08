"""Consultas de cronogramas, versiones y generaciones (F3)."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import exists, func, or_, select, text
from sqlalchemy.orm import Session, selectinload

from app.models import (
    AmbienteDiario,
    Cronograma,
    CronogramaCiclo,
    CronogramaEvento,
    CronogramaTurno,
    CronogramaVersion,
    Modulo,
    ModeloVersion,
    MotivoCorreccion,
    PrediccionEntrada,
    RiegoRegistro,
    Usuario,
)
from app.models.enums import EstadoCronograma, TipoEventoCronograma


def tomar_candado_generacion(db: Session, modulo_id: int) -> bool:
    """Candado de transacción por módulo (sirve con el pooler: se libera al terminar la transacción)."""
    return bool(db.execute(
        text("SELECT pg_try_advisory_xact_lock(hashtext('riego.generar'), CAST(:m AS integer))"),
        {"m": modulo_id},
    ).scalar())


def bloquear_rango(db: Session, modulo_id: int, fechas: Sequence[dt.date]) -> dict[dt.date, Cronograma]:
    filas = db.scalars(
        select(Cronograma)
        .where(Cronograma.modulo_id == modulo_id, Cronograma.fecha.in_(list(fechas)))
        .with_for_update()
    )
    return {c.fecha: c for c in filas}


def obtener(db: Session, cronograma_id: int, *, bloquear: bool = False) -> Cronograma | None:
    consulta = select(Cronograma).where(Cronograma.id == cronograma_id)
    if bloquear:
        consulta = consulta.with_for_update().execution_options(populate_existing=True)
    return db.scalars(consulta).first()


def por_fecha(db: Session, modulo_id: int, fecha: dt.date) -> Cronograma | None:
    return db.scalars(select(Cronograma).where(Cronograma.modulo_id == modulo_id, Cronograma.fecha == fecha)).first()


def listar(
    db: Session, modulo_id: int, desde: dt.date, hasta: dt.date, *, solo_publicados: bool = False,
    estado: EstadoCronograma | None = None,
) -> list[Cronograma]:
    consulta = select(Cronograma).where(
        Cronograma.modulo_id == modulo_id, Cronograma.fecha >= desde, Cronograma.fecha <= hasta
    )
    if solo_publicados:
        consulta = consulta.where(Cronograma.version_publicada_id.is_not(None))
    if estado is not None:
        consulta = consulta.where(Cronograma.estado == estado)
    return list(db.scalars(consulta.order_by(Cronograma.fecha.desc())))


def version(db: Session, version_id: int | None) -> CronogramaVersion | None:
    if version_id is None:
        return None
    return db.scalars(
        select(CronogramaVersion)
        .where(CronogramaVersion.id == version_id)
        .options(selectinload(CronogramaVersion.turnos), selectinload(CronogramaVersion.ciclos))
    ).first()


def versiones(db: Session, cronograma_id: int) -> list[CronogramaVersion]:
    return list(db.scalars(
        select(CronogramaVersion).where(CronogramaVersion.cronograma_id == cronograma_id)
        .order_by(CronogramaVersion.numero.desc())
    ))


def versiones_por_id(db: Session, ids: Iterable[int | None]) -> dict[int, CronogramaVersion]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return {v.id: v for v in db.scalars(select(CronogramaVersion).where(CronogramaVersion.id.in_(ids)))}


def version_por_numero(db: Session, cronograma_id: int, numero: int) -> CronogramaVersion | None:
    fila = db.scalars(select(CronogramaVersion.id).where(
        CronogramaVersion.cronograma_id == cronograma_id, CronogramaVersion.numero == numero
    )).first()
    return version(db, fila)


def max_numero(db: Session, cronograma_id: int) -> int:
    return db.execute(
        select(func.coalesce(func.max(CronogramaVersion.numero), 0)).where(CronogramaVersion.cronograma_id == cronograma_id)
    ).scalar_one()


def insertar_turnos(db: Session, filas: Sequence[dict[str, Any]]) -> None:
    if filas:
        db.execute(CronogramaTurno.__table__.insert(), list(filas))


def insertar_ciclos(db: Session, filas: Sequence[dict[str, Any]]) -> None:
    if filas:
        db.execute(CronogramaCiclo.__table__.insert(), list(filas))


def estado_registros(db: Session, modulo_id: int, fechas: Iterable[dt.date]) -> dict[tuple[int, dt.date], str]:
    """``(turno_id, fecha) -> estado`` del riego vigente (aplicado / provisional)."""
    fechas = list(set(fechas))
    if not fechas:
        return {}
    filas = db.execute(
        select(RiegoRegistro.turno_id, RiegoRegistro.fecha, RiegoRegistro.estado)
        .where(RiegoRegistro.modulo_id == modulo_id, RiegoRegistro.vigente.is_(True),
               RiegoRegistro.fecha.in_(fechas))
    )
    return {(t, f): e.value for t, f, e in filas}


def dias_con_riego_antes(db: Session, modulo_id: int, fecha: dt.date) -> int:
    return db.execute(
        select(func.count(func.distinct(RiegoRegistro.fecha))).where(
            RiegoRegistro.modulo_id == modulo_id, RiegoRegistro.vigente.is_(True), RiegoRegistro.fecha < fecha
        )
    ).scalar_one()


def desactualizado(db: Session, modulo: Modulo, fecha: dt.date, creada: dt.datetime) -> bool:
    """§3.3: hay riego de D-30..D-1 o ambiente de D-14..D-1 creado (o actualizado) después de la versión."""
    riego = exists().where(
        RiegoRegistro.modulo_id == modulo.id,
        RiegoRegistro.fecha >= fecha - dt.timedelta(days=30), RiegoRegistro.fecha < fecha,
        RiegoRegistro.created_at > creada,
    )
    ambiente = exists().where(
        AmbienteDiario.fundo_id == modulo.fundo_id,
        AmbienteDiario.fecha >= fecha - dt.timedelta(days=14), AmbienteDiario.fecha < fecha,
        or_(AmbienteDiario.created_at > creada, AmbienteDiario.updated_at > creada),
    )
    return bool(db.execute(select(or_(riego, ambiente))).scalar())


def nombres_modelo(db: Session, ids: Iterable[int | None]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(ModeloVersion.id, ModeloVersion.version).where(ModeloVersion.id.in_(ids))).all())


def motivo_activo(db: Session, codigo: str) -> bool:
    return bool(db.scalar(select(exists().where(
        MotivoCorreccion.codigo == codigo, MotivoCorreccion.activo.is_(True)
    ))))


def alternativas(db: Session, generacion_id: int, fecha: dt.date) -> dict[int, Any]:
    return dict(db.execute(select(PrediccionEntrada.turno_id, PrediccionEntrada.alternativas_n).where(
        PrediccionEntrada.generacion_id == generacion_id, PrediccionEntrada.fecha == fecha
    )).all())


def ultimo_evento(db: Session, cronograma_id: int, tipo: TipoEventoCronograma,
                  usuario_id: int, version_id: int) -> dt.datetime | None:
    return db.scalar(select(CronogramaEvento.ocurrido_at).where(
        CronogramaEvento.cronograma_id == cronograma_id, CronogramaEvento.tipo == tipo,
        CronogramaEvento.usuario_id == usuario_id, CronogramaEvento.version_id == version_id,
    ).order_by(CronogramaEvento.ocurrido_at.desc(), CronogramaEvento.id.desc()).limit(1))


def eventos(db: Session, cronograma_id: int) -> list[dict[str, Any]]:
    filas = db.execute(select(
        CronogramaEvento.tipo, CronogramaEvento.ocurrido_at, Usuario.username.label("usuario"),
        CronogramaVersion.numero.label("version_numero"), CronogramaEvento.motivo_codigo,
        CronogramaEvento.comentario, CronogramaEvento.detalle,
    ).outerjoin(Usuario, Usuario.id == CronogramaEvento.usuario_id)
        .outerjoin(CronogramaVersion, CronogramaVersion.id == CronogramaEvento.version_id)
        .where(CronogramaEvento.cronograma_id == cronograma_id)
        .order_by(CronogramaEvento.ocurrido_at.desc(), CronogramaEvento.id.desc()))
    return [dict(f) for f in filas.mappings()]


def datos_campo(db: Session, fundo_id: int, desde: dt.date, hasta: dt.date) -> list[dict[str, Any]]:
    """Conserva los nombres del modelo; omite IDs internos y marcas de persistencia."""
    columnas = [c for c in AmbienteDiario.__table__.columns if c.name not in {
        "id", "created_at", "updated_at",
    }]
    filas = db.execute(select(*columnas).where(
        AmbienteDiario.fundo_id == fundo_id, AmbienteDiario.fecha >= desde, AmbienteDiario.fecha < hasta,
    ).order_by(AmbienteDiario.fecha))
    return [dict(f) for f in filas.mappings()]


def numero_ultimo_visto(db: Session, cronograma_id: int, usuario_id: int) -> int | None:
    return db.scalar(
        select(CronogramaVersion.numero)
        .join(CronogramaEvento, CronogramaEvento.version_id == CronogramaVersion.id)
        .where(CronogramaEvento.cronograma_id == cronograma_id, CronogramaEvento.usuario_id == usuario_id,
               CronogramaEvento.tipo == TipoEventoCronograma.visto_programador)
        .order_by(CronogramaEvento.ocurrido_at.desc(), CronogramaEvento.id.desc()).limit(1)
    )
