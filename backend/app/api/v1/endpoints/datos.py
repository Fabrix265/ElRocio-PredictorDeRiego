"""Datos de campo: frescura (§3.3) y series (§4 "Datos de campo, panel e ingesta").

| Ruta | Quién |
|---|---|
| ``GET /datos/frescura?modulo_id&fecha&dias`` | todos |
| ``GET /datos/clima?desde&hasta&resolucion=diaria|30min`` | todos |
| ``GET /datos/suelo?desde&hasta&resolucion=diaria|horaria`` | todos |
| ``GET /datos/planta?desde&hasta`` | todos |
| ``GET /datos/pronostico?desde&hasta&capturado`` | todos |

Solo lectura. Las series van por defecto de los últimos 14 días cerrados (hasta ayer, hora de
Lima), en las unidades del modelo (°C, mm, km, kPa, W/m², % vol., µm).
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from app.api.deps import MAX_ID_BD, DbSesion, IdQuery, UsuarioHabilitado
from app.schemas.datos import FrescuraSalida, SerieSalida
from app.services import datos_service

router = APIRouter(prefix="/datos")

Desde = Annotated[dt.date | None, Query(description="AAAA-MM-DD (por defecto, 14 días antes de «hasta»)")]
Hasta = Annotated[dt.date | None, Query(description="AAAA-MM-DD, inclusivo (por defecto, ayer)")]


@router.get("/frescura", response_model=FrescuraSalida)
def frescura(
    _usuario: UsuarioHabilitado,
    db: DbSesion,
    modulo_id: Annotated[int, Query(ge=1, le=MAX_ID_BD)],
    fecha: Annotated[dt.date | None, Query(description="Día de trabajo (por defecto hoy); se evalúa hasta D-1")] = None,
    dias: Annotated[int, Query(ge=1, le=datos_service.MAX_DIAS_FRESCURA)] = datos_service.DIAS_FRESCURA,
) -> FrescuraSalida:
    return datos_service.frescura(db, modulo_id, fecha, dias)


@router.get("/clima", response_model=SerieSalida)
def clima(
    _usuario: UsuarioHabilitado,
    db: DbSesion,
    desde: Desde = None,
    hasta: Hasta = None,
    resolucion: Literal["diaria", "30min"] = "diaria",
    modulo_id: IdQuery = None,
) -> SerieSalida:
    """Diaria = ``ambiente_diario``; 30min = ``meteo_lectura`` (máx. 31 días)."""
    return datos_service.serie_clima(db, desde=desde, hasta=hasta, resolucion=resolucion, modulo_id=modulo_id)


@router.get("/suelo", response_model=SerieSalida)
def suelo(
    _usuario: UsuarioHabilitado,
    db: DbSesion,
    desde: Desde = None,
    hasta: Hasta = None,
    resolucion: Literal["diaria", "horaria"] = "diaria",
    modulo_id: IdQuery = None,
) -> SerieSalida:
    """Diaria = resumen de ``ambiente_diario``; horaria = ``phytech_suelo_horario`` (máx. 31 días)."""
    return datos_service.serie_suelo(db, desde=desde, hasta=hasta, resolucion=resolucion, modulo_id=modulo_id)


@router.get("/planta", response_model=SerieSalida)
def planta(_usuario: UsuarioHabilitado, db: DbSesion, desde: Desde = None, hasta: Hasta = None) -> SerieSalida:
    return datos_service.serie_planta(db, desde=desde, hasta=hasta)


@router.get("/pronostico", response_model=SerieSalida)
def pronostico(
    _usuario: UsuarioHabilitado,
    db: DbSesion,
    desde: Annotated[dt.date | None, Query()] = None,
    hasta: Annotated[dt.date | None, Query()] = None,
    capturado: Annotated[dt.date | None, Query(description="Fecha de captura (por defecto la última)")] = None,
) -> SerieSalida:
    return datos_service.serie_pronostico(db, desde=desde, hasta=hasta, capturado=capturado)
