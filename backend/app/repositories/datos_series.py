"""Consultas de lectura de los datos de campo: frescura por fuente (§3.3), series para gráficos
(§4 "Datos de campo") y caudal reciente por turno."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import (
    AmbienteDiario,
    MeteoLectura,
    NdviImagen,
    PhytechPlantaDiario,
    PhytechSueloHorario,
    PronosticoClima,
    RiegoCiclo,
    RiegoRegistro,
    Turno,
)
from app.models.enums import EstadoRiego

# --- Riego por turno-día --------------------------------------------------------


def turnos_activos(db: Session, modulo_id: int) -> list[Turno]:
    return list(db.scalars(
        select(Turno).where(Turno.modulo_id == modulo_id, Turno.activo.is_(True))
        .order_by(Turno.orden, Turno.id)
    ))


def ultimo_riego_por_turno(
    db: Session, modulo_id: int, hasta: dt.date, *, solo_aplicado: bool
) -> dict[int, dt.date]:
    """``turno_id -> última fecha <= hasta`` con registro vigente (aplicado, o cualquiera)."""
    consulta = (
        select(RiegoRegistro.turno_id, func.max(RiegoRegistro.fecha))
        .where(RiegoRegistro.modulo_id == modulo_id, RiegoRegistro.vigente.is_(True),
               RiegoRegistro.fecha <= hasta)
        .group_by(RiegoRegistro.turno_id)
    )
    if solo_aplicado:
        consulta = consulta.where(RiegoRegistro.estado == EstadoRiego.aplicado)
    return {t: f for t, f in db.execute(consulta)}


def riego_en_ventana(
    db: Session, modulo_id: int, desde: dt.date, hasta: dt.date
) -> list[tuple[int, dt.date, EstadoRiego]]:
    """``(turno_id, fecha, estado)`` de los registros vigentes con ``desde <= fecha <= hasta``."""
    return [tuple(f) for f in db.execute(
        select(RiegoRegistro.turno_id, RiegoRegistro.fecha, RiegoRegistro.estado)
        .where(RiegoRegistro.modulo_id == modulo_id, RiegoRegistro.vigente.is_(True),
               RiegoRegistro.fecha >= desde, RiegoRegistro.fecha <= hasta)
    )]


# --- Ambiente diario (WeatherLink, Phytech suelo y planta) ---------------------

CONDICIONES_AMBIENTE = {
    "weatherlink": AmbienteDiario.tiene_meteo == 1,
    "phytech_suelo": AmbienteDiario.hum_zona_radicular_cierre.is_not(None),
    "phytech_planta": AmbienteDiario.tiene_planta == 1,
}


def ultima_fecha_ambiente(db: Session, fundo_id: int, fuente: str, hasta: dt.date) -> dt.date | None:
    return db.scalar(
        select(func.max(AmbienteDiario.fecha))
        .where(AmbienteDiario.fundo_id == fundo_id, AmbienteDiario.fecha <= hasta,
               CONDICIONES_AMBIENTE[fuente])
    )


def fechas_ambiente(db: Session, fundo_id: int, fuente: str, desde: dt.date, hasta: dt.date) -> set[dt.date]:
    return set(db.scalars(
        select(AmbienteDiario.fecha)
        .where(AmbienteDiario.fundo_id == fundo_id, AmbienteDiario.fecha >= desde,
               AmbienteDiario.fecha <= hasta, CONDICIONES_AMBIENTE[fuente])
    ))


def ultima_ndvi(db: Session, fundo_id: int, plot_id: int, hasta: dt.date) -> dt.date | None:
    return db.scalar(select(func.max(NdviImagen.fecha))
                     .where(NdviImagen.fundo_id == fundo_id, NdviImagen.plot_id == plot_id,
                            NdviImagen.fecha <= hasta))


def ultima_captura(db: Session, project_id: int, hasta: dt.date) -> dt.date | None:
    return db.scalar(select(func.max(PronosticoClima.capturado_fecha))
                     .where(PronosticoClima.project_id == project_id,
                            PronosticoClima.capturado_fecha <= hasta))


# --- Series ---------------------------------------------------------------------


def ambiente(db: Session, fundo_id: int, desde: dt.date, hasta: dt.date) -> list[AmbienteDiario]:
    return list(db.scalars(
        select(AmbienteDiario)
        .where(AmbienteDiario.fundo_id == fundo_id, AmbienteDiario.fecha >= desde,
               AmbienteDiario.fecha <= hasta)
        .order_by(AmbienteDiario.fecha)
    ))


def meteo(db: Session, fundo_id: int, desde: dt.datetime, hasta: dt.datetime) -> list[MeteoLectura]:
    """Lecturas con ``desde <= fecha_hora < hasta``."""
    return list(db.scalars(
        select(MeteoLectura)
        .where(MeteoLectura.fundo_id == fundo_id, MeteoLectura.fecha_hora >= desde,
               MeteoLectura.fecha_hora < hasta)
        .order_by(MeteoLectura.fecha_hora)
    ))


def suelo(db: Session, project_id: int, desde: dt.datetime, hasta: dt.datetime) -> list[PhytechSueloHorario]:
    return list(db.scalars(
        select(PhytechSueloHorario)
        .where(PhytechSueloHorario.project_id == project_id, PhytechSueloHorario.fecha_hora >= desde,
               PhytechSueloHorario.fecha_hora < hasta)
        .order_by(PhytechSueloHorario.fecha_hora)
    ))


def planta(db: Session, project_id: int, desde: dt.date, hasta: dt.date) -> list[PhytechPlantaDiario]:
    return list(db.scalars(
        select(PhytechPlantaDiario)
        .where(PhytechPlantaDiario.project_id == project_id, PhytechPlantaDiario.fecha >= desde,
               PhytechPlantaDiario.fecha <= hasta)
        .order_by(PhytechPlantaDiario.fecha)
    ))


def pronostico(
    db: Session, project_id: int, capturado: dt.date, desde: dt.date | None, hasta: dt.date | None
) -> list[PronosticoClima]:
    consulta = select(PronosticoClima).where(PronosticoClima.project_id == project_id,
                                            PronosticoClima.capturado_fecha == capturado)
    if desde is not None:
        consulta = consulta.where(PronosticoClima.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(PronosticoClima.fecha <= hasta)
    return list(db.scalars(consulta.order_by(PronosticoClima.fecha)))


# --- Caudal reciente ------------------------------------------------------------


def caudal_reciente(db: Session, modulo_id: int, desde: dt.date, hasta: dt.date) -> dict[int, dict[str, Any]]:
    """Por turno, con los ciclos de riego **aplicado** vigente de ``desde..hasta``: mediana del
    caudal (m3/h = m3 / horas) y del factor de duración (min por m3/ha), y cuántos ciclos."""
    duracion_h = RiegoCiclo.duracion_min / 60.0
    filas = db.execute(
        select(
            RiegoRegistro.turno_id,
            func.percentile_cont(0.5).within_group(RiegoCiclo.riego_m3 / duracion_h).label("caudal"),
            func.percentile_cont(0.5).within_group(RiegoCiclo.duracion_min / RiegoCiclo.riego_m3ha)
            .label("factor"),
            func.count().label("ciclos"),
            func.max(RiegoRegistro.fecha).label("ultima"),
        )
        .join(RiegoCiclo, RiegoCiclo.registro_id == RiegoRegistro.id)
        .where(RiegoRegistro.modulo_id == modulo_id, RiegoRegistro.vigente.is_(True),
               RiegoRegistro.estado == EstadoRiego.aplicado, RiegoRegistro.fecha >= desde,
               RiegoRegistro.fecha <= hasta,
               and_(RiegoCiclo.duracion_min > 0, RiegoCiclo.riego_m3 > 0, RiegoCiclo.riego_m3ha > 0))
        .group_by(RiegoRegistro.turno_id)
    )
    return {f.turno_id: {"caudal_m3h": f.caudal, "factor_min_por_m3ha": f.factor, "ciclos": f.ciclos,
                         "ultima_fecha": f.ultima} for f in filas}
