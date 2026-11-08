"""Consultas de la ingesta de APIs: corridas, payloads crudos, última fecha guardada por fuente y
pronóstico."""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from typing import Any

from sqlalchemy import Date, cast, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    IngestaCorrida,
    IngestaCrudo,
    MeteoLectura,
    NdviImagen,
    PhytechPlantaDiario,
    PhytechSueloHorario,
    PronosticoClima,
    Usuario,
)
from app.models.enums import DisparoIngesta, EstadoIngesta
from app.repositories.datos_campo import ConteoUpsert, upsert

# --- Corridas -------------------------------------------------------------------


TIPO_INTERRUMPIDA = "interrumpida"


def reclamar_programada(
    db: Session, fuente: str, fecha: dt.date, inicio_at: dt.datetime, *, solo_interrumpida: bool = False
) -> int | None:
    """Crea la corrida programada de ``(fuente, fecha)`` si nadie la creó antes
    (``INSERT … ON CONFLICT``: exclusión entre procesos sin candados de sesión). Si la de ese día
    terminó en ``error`` se vuelve a reclamar (se reinicia la fila): así, al arrancar, se repite la
    ingesta del día que falló; con ``solo_interrumpida``, solo si el error fue que quedó sin
    terminar (el vigilante no repite cada pocos minutos un error de la API). Devuelve el id, o
    ``None`` si ya existe (en curso, ok o parcial) o si la fuente tiene otra corrida en curso (p. ej.
    un "Actualizar ahora": índice único parcial ``uq_ingesta_corrida_en_curso``)."""
    if en_curso(db, [fuente]):
        return None
    tabla = IngestaCorrida.__table__
    sentencia = insert(tabla).values(
        fuente=fuente, disparo=DisparoIngesta.programado, fecha_programada=fecha,
        inicio_at=inicio_at, latido_at=inicio_at, estado=EstadoIngesta.en_curso,
    )
    repetir = tabla.c.estado == EstadoIngesta.error
    if solo_interrumpida:
        repetir = repetir & tabla.c.errores.contains([{"tipo": TIPO_INTERRUMPIDA}])
    sentencia = sentencia.on_conflict_do_update(
        index_elements=["fuente", "fecha_programada"],
        set_={"estado": EstadoIngesta.en_curso, "inicio_at": inicio_at, "latido_at": inicio_at,
              "fin_at": None, "duracion_ms": None, "desde": None, "hasta": None, "filas_nuevas": 0,
              "filas_actualizadas": 0, "filas_omitidas": 0, "conflictos": 0,
              "errores": []},
        where=repetir,
    ).returning(tabla.c.id)
    try:
        with db.begin_nested():
            return db.execute(sentencia).scalar_one_or_none()
    except IntegrityError:
        return None  # otra corrida de la fuente empezó entre la consulta y el INSERT


def en_curso(db: Session, fuentes: Sequence[str]) -> list[IngestaCorrida]:
    return list(db.scalars(
        select(IngestaCorrida).where(IngestaCorrida.fuente.in_(list(fuentes)),
                                     IngestaCorrida.estado == EstadoIngesta.en_curso)
    ))


def cerrar_colgadas(db: Session, antes_de: dt.datetime, ahora: dt.datetime) -> list[tuple[int, str, dt.date | None]]:
    """Corridas ``en_curso`` cuyo último latido (o inicio, si nunca latió) es anterior a
    ``antes_de``: nadie las está ejecutando (el proceso murió o no pudo guardarlas). Quedan en
    ``error`` con tipo ``interrumpida``. Devuelve ``(id, fuente, fecha_programada)`` de cada una."""
    resultado = db.execute(
        update(IngestaCorrida)
        .where(IngestaCorrida.estado == EstadoIngesta.en_curso,
               func.coalesce(IngestaCorrida.latido_at, IngestaCorrida.inicio_at) < antes_de)
        .values(estado=EstadoIngesta.error, fin_at=ahora,
                errores=[{"tipo": TIPO_INTERRUMPIDA, "status_code": None, "endpoint": None,
                          "mensaje": "La corrida quedó sin terminar (proceso detenido)"}])
        .returning(IngestaCorrida.id, IngestaCorrida.fuente, IngestaCorrida.fecha_programada)
        .execution_options(synchronize_session=False)
    )
    return [tuple(fila) for fila in resultado]


def marcar_latido(db: Session, corrida_id: int, ahora: dt.datetime) -> bool:
    """Latido de una corrida en curso (transacción corta y aparte de la de la ingesta). Espera como
    mucho unos segundos un candado de la fila: si no lo obtiene, lo intentará en el próximo."""
    db.execute(text("SET LOCAL lock_timeout = '5s'"))
    resultado = db.execute(
        update(IngestaCorrida)
        .where(IngestaCorrida.id == corrida_id, IngestaCorrida.estado == EstadoIngesta.en_curso)
        .values(latido_at=ahora)
        .execution_options(synchronize_session=False)
    )
    return bool(resultado.rowcount)


def listar(db: Session, *, limite: int, fuente: str | None = None) -> list[tuple[IngestaCorrida, str | None]]:
    """Corridas más recientes primero, con el username de quien la lanzó."""
    consulta = (
        select(IngestaCorrida, Usuario.username)
        .outerjoin(Usuario, Usuario.id == IngestaCorrida.usuario_id)
        .order_by(IngestaCorrida.inicio_at.desc(), IngestaCorrida.id.desc())
        .limit(limite)
    )
    if fuente:
        consulta = consulta.where(IngestaCorrida.fuente == fuente)
    return [(c, u) for c, u in db.execute(consulta)]


def username(db: Session, usuario_id: int | None) -> str | None:
    if usuario_id is None:
        return None
    return db.scalar(select(Usuario.username).where(Usuario.id == usuario_id))


# --- Crudo ----------------------------------------------------------------------


def guardar_crudo(db: Session, corrida_id: int, endpoint: str, parametros: dict[str, Any], payload: Any) -> None:
    db.add(IngestaCrudo(corrida_id=corrida_id, endpoint=endpoint[:255], parametros=parametros, payload=payload))


def crudos_weatherlink(db: Session, desde: dt.date, hasta: dt.date) -> list[IngestaCrudo]:
    """El último payload guardado de cada día de WeatherLink con ``desde <= dia <= hasta``
    (``parametros.dia``; las corridas de ``reprocesar`` no guardan crudo)."""
    dia = IngestaCrudo.parametros["dia"].astext
    ultimos = (
        select(func.max(IngestaCrudo.id))
        .join(IngestaCorrida, IngestaCorrida.id == IngestaCrudo.corrida_id)
        .where(IngestaCorrida.fuente == "weatherlink", dia >= desde.isoformat(), dia <= hasta.isoformat())
        .group_by(dia)
    )
    return list(db.scalars(select(IngestaCrudo).where(IngestaCrudo.id.in_(ultimos)).order_by(IngestaCrudo.id)))


# --- Última fecha guardada por fuente -------------------------------------------


def ultima_meteo(db: Session, fundo_id: int) -> dt.date | None:
    return db.scalar(select(func.max(cast(MeteoLectura.fecha_hora, Date)))
                     .where(MeteoLectura.fundo_id == fundo_id))


def ultima_suelo(db: Session, project_id: int) -> dt.date | None:
    return db.scalar(select(func.max(cast(PhytechSueloHorario.fecha_hora, Date)))
                     .where(PhytechSueloHorario.project_id == project_id,
                            PhytechSueloHorario.hay_dato.is_(True)))


def ultima_planta(db: Session, project_id: int) -> dt.date | None:
    return db.scalar(select(func.max(PhytechPlantaDiario.fecha))
                     .where(PhytechPlantaDiario.project_id == project_id,
                            PhytechPlantaDiario.mds_contraccion_um.is_not(None)))


def ultima_ndvi(db: Session, fundo_id: int, plot_id: int) -> dt.date | None:
    return db.scalar(select(func.max(NdviImagen.fecha))
                     .where(NdviImagen.fundo_id == fundo_id, NdviImagen.plot_id == plot_id))


def ultima_captura_pronostico(db: Session, project_id: int, *, hasta: dt.date | None = None) -> dt.date | None:
    consulta = select(func.max(PronosticoClima.capturado_fecha)).where(PronosticoClima.project_id == project_id)
    if hasta is not None:
        consulta = consulta.where(PronosticoClima.capturado_fecha <= hasta)
    return db.scalar(consulta)


def dias_meteo(db: Session, fundo_id: int, desde: dt.date, hasta: dt.date, minimo: int) -> set[dt.date]:
    """Días de ``desde..hasta`` con al menos ``minimo`` lecturas meteorológicas (cualquier origen)."""
    dia = cast(MeteoLectura.fecha_hora, Date)
    return set(db.scalars(
        select(dia).where(MeteoLectura.fundo_id == fundo_id, dia >= desde, dia <= hasta)
        .group_by(dia).having(func.count() >= minimo)
    ))


def dias_suelo(db: Session, project_id: int, desde: dt.date, hasta: dt.date) -> set[dt.date]:
    dia = cast(PhytechSueloHorario.fecha_hora, Date)
    return set(db.scalars(
        select(dia).distinct().where(PhytechSueloHorario.project_id == project_id,
                                     PhytechSueloHorario.hay_dato.is_(True), dia >= desde, dia <= hasta)
    ))


def dias_planta(db: Session, project_id: int, desde: dt.date, hasta: dt.date) -> set[dt.date]:
    return set(db.scalars(
        select(PhytechPlantaDiario.fecha).where(
            PhytechPlantaDiario.project_id == project_id, PhytechPlantaDiario.mds_contraccion_um.is_not(None),
            PhytechPlantaDiario.fecha >= desde, PhytechPlantaDiario.fecha <= hasta)
    ))


# --- Pronóstico -----------------------------------------------------------------

COLUMNAS_PRONOSTICO = ("t_max", "eto_mm", "etc_mm", "humedad")


def upsert_pronostico(db: Session, filas: Sequence[dict[str, Any]]) -> ConteoUpsert:
    return upsert(
        db, PronosticoClima, filas, conflicto=("project_id", "capturado_fecha", "fecha"),
        columnas_valor=("fundo_id", *COLUMNAS_PRONOSTICO), columnas_extra=("corrida_id",),
    )
