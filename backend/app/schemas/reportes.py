"""Esquemas de reportes (F5): agua aplicada vs propuesta y KPIs del Dashboard."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel

from app.schemas.datos import SerieSalida


class AguaTurno(BaseModel):
    turno_id: int
    turno_codigo: str
    area_ha: float
    aplicado_m3ha: float | None = None
    aplicado_m3: float | None = None
    estado_riego: str | None = None  # aplicado · provisional · None (sin registro)
    sin_riego: bool = False
    propuesto_m3ha: float | None = None  # versión publicada (A E S: si no hay, el borrador)
    propuesto_m3: float | None = None
    modelo_m3ha: float | None = None  # última versión del modelo (nunca para el programador)
    modelo_m3: float | None = None


class AguaDia(BaseModel):
    fecha: dt.date
    cronograma_id: int | None = None
    turnos: list[AguaTurno]


class AguaSalida(BaseModel):
    modulo_id: int
    desde: dt.date
    hasta: dt.date
    con_modelo: bool
    dias: list[AguaDia]


class DashboardSalida(BaseModel):
    modulo_id: int
    fecha: dt.date
    ayer: dt.date
    agua_aplicada_m3ha: float | None = None
    agua_aplicada_m3: float | None = None
    turnos_con_riego: int
    turnos_total: int
    aplicado_vs_modelo_pct: float | None = None
    mds_um: float | None = None
    eto_mm: float | None = None
    estado_manana: str | None = None
    cronograma_manana_id: int | None = None
    pronostico: SerieSalida
