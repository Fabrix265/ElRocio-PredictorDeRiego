"""Riego aplicado: consulta por módulo y rango, e historial de versiones de un turno-día (§4).

La edición manual del provisional y "marcar aplicado" llegan en F4; la carga de Excel está en
:mod:`app.services.carga_riego_service`.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from app.core.errores import DatosInvalidos, NoEncontrado
from app.core.tiempo import fuera_de_limites, hoy_lima, mensaje_fuera_de_limites
from app.models import Modulo, RiegoRegistro, Turno
from app.repositories import riego as repo

DIAS_POR_DEFECTO = 14
MAX_DIAS_RANGO = 366


def rango(desde: dt.date | None, hasta: dt.date | None) -> tuple[dt.date, dt.date]:
    """Rango inclusivo; por defecto los últimos 14 días hasta hoy (Lima)."""
    if fuera_de_limites(desde, hasta) is not None:
        raise DatosInvalidos(mensaje_fuera_de_limites())
    hasta = hasta or hoy_lima()
    desde = desde or hasta - dt.timedelta(days=DIAS_POR_DEFECTO - 1)
    if desde > hasta:
        raise DatosInvalidos("La fecha desde debe ser igual o anterior a la fecha hasta.")
    if (hasta - desde).days + 1 > MAX_DIAS_RANGO:
        raise DatosInvalidos(f"El rango máximo es de {MAX_DIAS_RANGO} días.")
    return desde, hasta


def _registro(registro: RiegoRegistro, turnos: dict[int, str], nombres: dict[int, str],
              *, con_version: bool = False) -> dict[str, Any]:
    salida = {
        "id": registro.id, "turno_id": registro.turno_id, "turno_codigo": turnos.get(registro.turno_id),
        "fecha": registro.fecha, "version": registro.version, "estado": registro.estado,
        "origen": registro.origen, "sin_riego": registro.sin_riego, "motivo": registro.motivo,
        "comentario": registro.comentario, "carga_id": registro.carga_id,
        "creado_at": registro.created_at.astimezone(dt.UTC) if registro.created_at else None,
        "creado_por": nombres.get(registro.creado_por),
        "ciclos": list(registro.ciclos),
    }
    if con_version:
        salida |= {"vigente": registro.vigente, "basado_en_id": registro.basado_en_id}
    return salida


def listar(db: Session, modulo_id: int, desde: dt.date | None, hasta: dt.date | None) -> dict[str, Any]:
    """Registros vigentes del módulo (día × turno × ciclos con estado) en ``[desde, hasta]``."""
    modulo = db.get(Modulo, modulo_id)
    if modulo is None:
        raise NoEncontrado("No existe el módulo indicado.")
    desde, hasta = rango(desde, hasta)
    registros = repo.vigentes(db, modulo.id, desde=desde, hasta=hasta + dt.timedelta(days=1))
    turnos = {t.id: t.codigo for t in repo.turnos_de_modulo(db, modulo.id)}
    nombres = repo.usernames(db, (r.creado_por for r in registros))
    return {
        "modulo_id": modulo.id, "desde": desde, "hasta": hasta,
        "registros": [_registro(r, turnos, nombres) for r in registros],
    }


def versiones(db: Session, turno_id: int, fecha: dt.date) -> list[dict[str, Any]]:
    """Todas las versiones del turno-día (la 1 es el original), de la más antigua a la vigente."""
    turno = db.get(Turno, turno_id)
    if turno is None:
        raise NoEncontrado("No existe el turno indicado.")
    registros = repo.versiones_turno_dia(db, turno.id, fecha)
    nombres = repo.usernames(db, (r.creado_por for r in registros))
    return [_registro(r, {turno.id: turno.codigo}, nombres, con_version=True) for r in registros]
