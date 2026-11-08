"""Consultas de datos de campo: lecturas de sensores, NDVI, ambiente diario y corridas de ingesta.

Las escrituras masivas usan ``INSERT … ON CONFLICT DO UPDATE … WHERE <algo cambió>``: repetir una
carga con los mismos datos no cambia nada (ni ``updated_at``). Cada upsert devuelve cuántas filas
insertó y cuántas actualizó (``xmax = 0`` distingue un INSERT de un UPDATE en Postgres).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import ColumnElement, Date, and_, cast, delete, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import (
    AmbienteDiario,
    Fundo,
    IngestaCorrida,
    MeteoLectura,
    Modulo,
    NdviImagen,
    PhytechPlantaDiario,
    PhytechSueloHorario,
)
from app.models.enums import OrigenMeteo
from app.repositories import masivo

LOTE_INSERT = 1000  # filas por sentencia (muy por debajo del límite de parámetros de Postgres)


@dataclass
class ConteoUpsert:
    nuevas: int = 0
    actualizadas: int = 0
    omitidas: int = 0  # ya estaban iguales (o protegidas, p. ej. Excel histórico frente a la API)

    def sumar(self, otro: ConteoUpsert) -> ConteoUpsert:
        return ConteoUpsert(
            self.nuevas + otro.nuevas, self.actualizadas + otro.actualizadas,
            self.omitidas + otro.omitidas,
        )


def upsert(
    db: Session,
    modelo: type,
    filas: Sequence[dict[str, Any]],
    *,
    conflicto: Sequence[str],
    columnas_valor: Sequence[str],
    columnas_extra: Sequence[str] = (),
    condicion: ColumnElement[bool] | None = None,
) -> ConteoUpsert:
    """Inserta o actualiza por la clave ``conflicto``.

    Solo actualiza si alguna de ``columnas_valor`` cambió (``IS DISTINCT FROM``) y se cumple
    ``condicion``; ``columnas_extra`` (origen, corrida) se escriben junto con el cambio pero no
    cuentan como cambio.
    """
    conteo = ConteoUpsert()
    if not filas:
        return conteo
    tabla = modelo.__table__
    columnas = list(filas[0].keys())
    masiva = masivo.admite_unnest(tabla, columnas)
    sentencia = masivo.insert_unnest(tabla, columnas) if masiva else insert(tabla)
    excluded = sentencia.excluded
    cambio = or_(*[tabla.c[c].is_distinct_from(excluded[c]) for c in columnas_valor])
    sentencia = sentencia.on_conflict_do_update(
        index_elements=list(conflicto),
        set_={c: excluded[c] for c in (*columnas_valor, *columnas_extra)},
        where=cambio if condicion is None else and_(cambio, condicion),
    ).returning(literal_column("(xmax = 0)").label("insertada"))
    tamano = masivo.LOTE if masiva else LOTE_INSERT
    for inicio in range(0, len(filas), tamano):
        lote = list(filas[inicio:inicio + tamano])
        parametros = masivo.parametros(columnas, lote) if masiva else lote
        resultados = [fila.insertada for fila in db.execute(sentencia, parametros)]
        nuevas = sum(1 for r in resultados if r)
        conteo.nuevas += nuevas
        conteo.actualizadas += len(resultados) - nuevas
        conteo.omitidas += len(lote) - len(resultados)
    return conteo


# --- Organización ---------------------------------------------------------------

def fundo_por_id(db: Session, fundo_id: int) -> Fundo | None:
    return db.get(Fundo, fundo_id)


def fundo_por_nombre(db: Session, nombre: str) -> Fundo | None:
    return db.scalars(select(Fundo).where(Fundo.nombre == nombre)).first()


def modulo_por_codigo(db: Session, codigo: str) -> Modulo | None:
    return db.scalars(select(Modulo).where(Modulo.codigo == codigo)).first()


# --- Meteorología ---------------------------------------------------------------

COLUMNAS_METEO = ("temp", "temp_max", "temp_min", "hr", "hr_max", "rad", "eto", "dpv", "viento", "lluvia")


def upsert_meteo(db: Session, filas: Sequence[dict[str, Any]]) -> ConteoUpsert:
    """Lecturas por ``(fundo_id, fecha_hora)``. Una lectura ``excel_historico`` nunca se pisa con
    una de otro origen (WeatherLink no reemplaza el Excel histórico)."""
    tabla = MeteoLectura.__table__
    protegida = and_(
        tabla.c.origen == OrigenMeteo.excel_historico,
        insert(tabla).excluded.origen != OrigenMeteo.excel_historico,
    )
    return upsert(
        db, MeteoLectura, filas, conflicto=("fundo_id", "fecha_hora"),
        columnas_valor=(*COLUMNAS_METEO, "origen"), columnas_extra=("corrida_id",),
        condicion=~protegida,
    )


def lecturas_meteo(db: Session, fundo_id: int, desde: dt.datetime, hasta: dt.datetime) -> list[Any]:
    """Lecturas con ``desde <= fecha_hora < hasta`` (hora local sin zona)."""
    return list(db.execute(
        select(MeteoLectura.fecha_hora, *[MeteoLectura.__table__.c[c] for c in COLUMNAS_METEO])
        .where(MeteoLectura.fundo_id == fundo_id, MeteoLectura.fecha_hora >= desde,
               MeteoLectura.fecha_hora < hasta)
        .order_by(MeteoLectura.fecha_hora)
    ))


# --- Phytech --------------------------------------------------------------------

COLUMNAS_SUELO = (
    "hay_dato", "hum_15cm", "hum_30cm", "hum_45cm", "hum_60cm", "hum_75cm", "hum_90cm",
    "temp_15cm", "temp_30cm", "temp_60cm", "temp_90cm", "hum_zona_radicular", "hum_saturacion",
    "hum_linea_estres", "hum_zona_radicular_norm_pct",
)
COLUMNAS_PLANTA = (
    "mds_contraccion_um", "crecimiento_tronco_um", "estres_planta_ps", "tamano_fruto_mm",
    "crecimiento_fruto_mm", "et_mm", "lluvia_mm",
)


def upsert_suelo(
    db: Session, filas: Sequence[dict[str, Any]], *, proteger_con_dato: bool = False
) -> ConteoUpsert:
    """``proteger_con_dato`` (ingesta de la API): una hora guardada con dato no se reemplaza por
    un hueco de la rejilla (``hay_dato = false``) si la API deja de devolverla."""
    tabla = PhytechSueloHorario.__table__
    condicion = None
    if proteger_con_dato:
        condicion = ~and_(tabla.c.hay_dato.is_(True), insert(tabla).excluded.hay_dato.is_(False))
    return upsert(
        db, PhytechSueloHorario, filas, conflicto=("project_id", "fecha_hora"),
        columnas_valor=("fundo_id", "plot_id", *COLUMNAS_SUELO), columnas_extra=("corrida_id",),
        condicion=condicion,
    )


def upsert_planta(
    db: Session, filas: Sequence[dict[str, Any]], columnas: Sequence[str] = COLUMNAS_PLANTA
) -> ConteoUpsert:
    """``columnas``: las mediciones que trae la fuente (las demás no se tocan)."""
    return upsert(
        db, PhytechPlantaDiario, filas, conflicto=("project_id", "fecha"),
        columnas_valor=("fundo_id", "plot_id", *columnas), columnas_extra=("corrida_id",),
    )


def suelo_horario(db: Session, project_id: int, desde: dt.datetime, hasta: dt.datetime) -> list[Any]:
    return list(db.execute(
        select(PhytechSueloHorario.project_id, PhytechSueloHorario.fecha_hora,
               *[PhytechSueloHorario.__table__.c[c] for c in COLUMNAS_SUELO])
        .where(PhytechSueloHorario.project_id == project_id,
               PhytechSueloHorario.fecha_hora >= desde, PhytechSueloHorario.fecha_hora < hasta)
        .order_by(PhytechSueloHorario.fecha_hora)
    ))


def planta_diario(db: Session, project_id: int, desde: dt.date, hasta: dt.date) -> list[Any]:
    """Filas con ``desde <= fecha <= hasta``."""
    return list(db.execute(
        select(PhytechPlantaDiario.project_id, PhytechPlantaDiario.fecha,
               *[PhytechPlantaDiario.__table__.c[c] for c in COLUMNAS_PLANTA])
        .where(PhytechPlantaDiario.project_id == project_id, PhytechPlantaDiario.fecha >= desde,
               PhytechPlantaDiario.fecha <= hasta)
        .order_by(PhytechPlantaDiario.fecha)
    ))


# --- NDVI -----------------------------------------------------------------------

COLUMNAS_NDVI = ("fundo_id", "area_id", "plot_id", "fecha", "no_vegetation", "clases", "ndvi_medio")


def upsert_ndvi(db: Session, filas: Sequence[dict[str, Any]]) -> ConteoUpsert:
    return upsert(
        db, NdviImagen, filas, conflicto=("image_id",), columnas_valor=COLUMNAS_NDVI,
        columnas_extra=("corrida_id",),
    )


def ndvi_imagenes(db: Session, fundo_id: int, plot_id: int, desde: dt.date, hasta: dt.date) -> list[NdviImagen]:
    return list(db.scalars(
        select(NdviImagen)
        .where(NdviImagen.fundo_id == fundo_id, NdviImagen.plot_id == plot_id,
               NdviImagen.fecha >= desde, NdviImagen.fecha <= hasta)
        .order_by(NdviImagen.fecha, NdviImagen.image_id)
    ))


# --- Ambiente diario ------------------------------------------------------------

def upsert_ambiente(db: Session, filas: Sequence[dict[str, Any]], columnas_valor: Sequence[str]) -> ConteoUpsert:
    return upsert(db, AmbienteDiario, filas, conflicto=("fundo_id", "fecha"), columnas_valor=columnas_valor)


def borrar_ambiente(db: Session, fundo_id: int, fechas: Iterable[dt.date]) -> int:
    fechas = list(fechas)
    if not fechas:
        return 0
    resultado = db.execute(
        delete(AmbienteDiario).where(AmbienteDiario.fundo_id == fundo_id, AmbienteDiario.fecha.in_(fechas))
    )
    return resultado.rowcount or 0


def ambiente(db: Session, fundo_id: int, *, desde: dt.date | None = None,
             hasta: dt.date | None = None) -> list[AmbienteDiario]:
    consulta = select(AmbienteDiario).where(AmbienteDiario.fundo_id == fundo_id)
    if desde is not None:
        consulta = consulta.where(AmbienteDiario.fecha >= desde)
    if hasta is not None:
        consulta = consulta.where(AmbienteDiario.fecha <= hasta)
    return list(db.scalars(consulta.order_by(AmbienteDiario.fecha)))


def fechas_con_datos(db: Session, fundo_id: int, project_id: int, plot_id: int) -> set[dt.date]:
    """Días con alguna lectura de meteo, suelo, planta o NDVI (para recalcular todo el ambiente)."""
    fecha_meteo = select(cast(MeteoLectura.fecha_hora, Date).distinct()).where(
        MeteoLectura.fundo_id == fundo_id
    )
    fecha_suelo = select(cast(PhytechSueloHorario.fecha_hora, Date).distinct()).where(
        PhytechSueloHorario.project_id == project_id
    )
    fechas: set[dt.date] = set()
    for consulta in (fecha_meteo, fecha_suelo):
        fechas |= set(db.scalars(consulta))
    fechas |= set(db.scalars(select(PhytechPlantaDiario.fecha).where(PhytechPlantaDiario.project_id == project_id)))
    fechas |= set(db.scalars(select(NdviImagen.fecha).where(NdviImagen.fundo_id == fundo_id,
                                                           NdviImagen.plot_id == plot_id)))
    return fechas


# --- Corridas de ingesta --------------------------------------------------------

def nueva_corrida(db: Session, **valores: Any) -> IngestaCorrida:
    corrida = IngestaCorrida(**valores)
    db.add(corrida)
    db.flush()
    return corrida
