"""Consultas del copiloto: tokens de servicio, sugerencias y respuesta diaria del suelo."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Date, cast, extract, func, select, text
from sqlalchemy.orm import Session

from app.models import (
    Auditoria,
    CopilotoSugerencia,
    Cronograma,
    CronogramaEvento,
    IngestaCorrida,
    Modulo,
    MotivoCorreccion,
    PhytechSueloHorario,
    TokenServicio,
    Turno,
    Usuario,
)
from app.models.enums import DisparoIngesta, TipoEventoCronograma

# --- Catálogo -------------------------------------------------------------------


def modulos_activos(db: Session) -> list[Modulo]:
    return list(db.scalars(select(Modulo).where(Modulo.activo.is_(True)).order_by(Modulo.codigo)))


def turno_por_codigo(db: Session, modulo_id: int, codigo: str) -> Turno | None:
    return db.scalars(select(Turno).where(Turno.modulo_id == modulo_id,
                                          func.upper(Turno.codigo) == codigo.strip().upper())).first()


# --- Tokens de servicio ---------------------------------------------------------


def token_activo_por_hash(db: Session, token_hash: str) -> TokenServicio | None:
    return db.scalars(select(TokenServicio).where(
        TokenServicio.token_hash == token_hash, TokenServicio.activo.is_(True)
    )).first()


def token_por_nombre(db: Session, nombre: str) -> TokenServicio | None:
    return db.scalars(select(TokenServicio).where(func.lower(TokenServicio.nombre) == nombre.lower())).first()


def tokens(db: Session) -> list[TokenServicio]:
    return list(db.scalars(select(TokenServicio).order_by(TokenServicio.id)))


# --- Sugerencias ----------------------------------------------------------------


def sugerencia(db: Session, sugerencia_id: int, *, bloquear: bool = False) -> CopilotoSugerencia | None:
    consulta = select(CopilotoSugerencia).where(CopilotoSugerencia.id == sugerencia_id)
    if bloquear:
        consulta = consulta.with_for_update().execution_options(populate_existing=True)
    return db.scalars(consulta).first()


def pendiente_igual(
    db: Session, *, modulo_id: int, fecha: dt.date, tipo: str, turno_id: int | None, alerta_codigo: str | None,
    titulo: str,
) -> CopilotoSugerencia | None:
    """La pendiente con la misma clave que ``uq_copiloto_sugerencia_pendiente`` (módulo, día, tipo,
    turno, alerta y título sin distinguir mayúsculas)."""
    consulta = select(CopilotoSugerencia).where(
        CopilotoSugerencia.estado == "pendiente", CopilotoSugerencia.modulo_id == modulo_id,
        CopilotoSugerencia.fecha == fecha, CopilotoSugerencia.tipo == tipo,
        func.lower(CopilotoSugerencia.titulo) == titulo.lower(),
    )
    consulta = consulta.where(CopilotoSugerencia.turno_id.is_(None) if turno_id is None
                              else CopilotoSugerencia.turno_id == turno_id)
    consulta = consulta.where(CopilotoSugerencia.alerta_codigo.is_(None) if alerta_codigo is None
                              else CopilotoSugerencia.alerta_codigo == alerta_codigo)
    return db.scalars(consulta.order_by(CopilotoSugerencia.id)).first()


def listar_sugerencias(
    db: Session, *, estado: str | None, modulo_id: int | None, limite: int,
) -> list[CopilotoSugerencia]:
    consulta = select(CopilotoSugerencia)
    if estado is not None:
        consulta = consulta.where(CopilotoSugerencia.estado == estado)
    if modulo_id is not None:
        consulta = consulta.where(CopilotoSugerencia.modulo_id == modulo_id)
    return list(db.scalars(consulta.order_by(CopilotoSugerencia.created_at.desc(), CopilotoSugerencia.id.desc())
                           .limit(limite)))


def contar_pendientes(db: Session, modulo_id: int | None = None) -> int:
    consulta = select(func.count()).select_from(CopilotoSugerencia).where(CopilotoSugerencia.estado == "pendiente")
    if modulo_id is not None:
        consulta = consulta.where(CopilotoSugerencia.modulo_id == modulo_id)
    return int(db.execute(consulta).scalar_one())


def turnos_por_id(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return dict(db.execute(select(Turno.id, Turno.codigo).where(Turno.id.in_(ids))).all())


def tokens_por_id(db: Session, ids: set[int]) -> dict[int, TokenServicio]:
    if not ids:
        return {}
    return {t.id: t for t in db.scalars(select(TokenServicio).where(TokenServicio.id.in_(ids)))}


def nombres_usuario(db: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return dict(db.execute(select(Usuario.id, Usuario.nombre).where(Usuario.id.in_(ids))).all())


# --- Respuesta del suelo al riego -----------------------------------------------


def humedad_diaria(db: Session, project_id: int, desde: dt.date, hasta: dt.date) -> dict[dt.date, dict[str, Any]]:
    """Por día: humedad de la zona radicular antes de las 06:00 (mínimo), máximo del día y número
    de lecturas, de ``phytech_suelo_horario`` (hora local de Lima, sin zona)."""
    dia = cast(PhytechSueloHorario.fecha_hora, Date)
    madrugada = extract("hour", PhytechSueloHorario.fecha_hora) < 6
    filas = db.execute(
        select(
            dia.label("fecha"),
            func.min(PhytechSueloHorario.hum_zona_radicular).filter(madrugada).label("inicio"),
            func.max(PhytechSueloHorario.hum_zona_radicular).label("maximo"),
            func.count(PhytechSueloHorario.hum_zona_radicular).label("lecturas"),
        )
        .where(
            PhytechSueloHorario.project_id == project_id,
            PhytechSueloHorario.fecha_hora >= dt.datetime.combine(desde, dt.time()),
            PhytechSueloHorario.fecha_hora < dt.datetime.combine(hasta + dt.timedelta(days=1), dt.time()),
        )
        .group_by(dia)
    )
    return {f.fecha: {"inicio": f.inicio, "maximo": f.maximo, "lecturas": f.lecturas} for f in filas}


# --- Avisos por Telegram ----------------------------------------------------------


def corridas_programadas(db: Session, fecha: dt.date) -> list[IngestaCorrida]:
    """Corridas de la ingesta programada de ``fecha`` (una por fuente: ``uq(fuente, fecha_programada)``)."""
    return list(db.scalars(select(IngestaCorrida).where(
        IngestaCorrida.disparo == DisparoIngesta.programado, IngestaCorrida.fecha_programada == fecha,
    )))


def claves_avisadas(db: Session, claves: Sequence[str], *, accion: str, entidad: str) -> set[str]:
    """Las claves de aviso que ya tienen su confirmación de envío en la auditoría."""
    if not claves:
        return set()
    return set(db.scalars(select(Auditoria.entidad_id).where(
        Auditoria.accion == accion, Auditoria.entidad == entidad, Auditoria.entidad_id.in_(list(claves)),
    )))


def bloquear_avisos(db: Session) -> None:
    """Candado de transacción (sirve con el pooler 6543): dos confirmaciones a la vez no duplican."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext('riego.copiloto_avisos'))"))


def eventos_cronograma(db: Session, modulo_id: int, desde: dt.datetime,
                       tipos: Sequence[TipoEventoCronograma]) -> list[Any]:
    """Eventos de los cronogramas del módulo desde ``desde`` (los más antiguos primero)."""
    return list(db.execute(
        select(CronogramaEvento, Cronograma)
        .join(Cronograma, Cronograma.id == CronogramaEvento.cronograma_id)
        .where(Cronograma.modulo_id == modulo_id, CronogramaEvento.ocurrido_at >= desde,
               CronogramaEvento.tipo.in_(list(tipos)))
        .order_by(CronogramaEvento.ocurrido_at, CronogramaEvento.id)
    ).all())


def usuarios_por_id(db: Session, ids: set[int]) -> dict[int, Usuario]:
    if not ids:
        return {}
    return {u.id: u for u in db.scalars(select(Usuario).where(Usuario.id.in_(ids)))}


def nombres_motivo(db: Session, codigos: set[str]) -> dict[str, str]:
    if not codigos:
        return {}
    filas = db.execute(select(MotivoCorreccion.codigo, MotivoCorreccion.nombre)
                       .where(MotivoCorreccion.codigo.in_(codigos))).all()
    return {codigo: nombre for codigo, nombre in filas}
