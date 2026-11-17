"""Esquemas de reportes (F5): agua aplicada vs propuesta y KPIs del Dashboard."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel

from app.schemas.datos import SerieSalida


class AguaTurno(BaseModel):
    turno_id: int
    turno_codigo: str
    area_ha: float
    # Riego vigente del turno-día (aplicado o, si aún no llegó el dato real, el provisional).
    aplicado_m3ha: float | None = None
    aplicado_m3: float | None = None
    estado_riego: str | None = None  # aplicado · provisional · None (sin registro)
    origen_riego: str | None = None  # controlador · historico · excel · manual · cronograma
    sin_riego: bool = False
    # Riego real: solo si el vigente está aplicado (controlador, histórico, Excel o manual).
    real_m3ha: float | None = None
    real_m3: float | None = None
    # La versión propuesta cambió el total o los ciclos del turno respecto del modelo.
    modificado: bool = False
    propuesto_m3ha: float | None = None  # versión publicada (A E S: si no hay, el borrador)
    propuesto_m3: float | None = None
    modelo_m3ha: float | None = None  # última versión del modelo (nunca para el programador)
    modelo_m3: float | None = None


class AguaDia(BaseModel):
    fecha: dt.date
    cronograma_id: int | None = None
    propuesta_version: int | None = None  # número de la versión publicada (o borrador)
    propuesta_origen: str | None = None  # modelo · regenerado · edicion · correccion
    propuesta_publicada: bool = False
    modelo_version: int | None = None  # nunca para el programador
    modificado: bool = False  # la propuesta es una edición/corrección distinta del modelo
    motivo: str | None = None  # motivo de la corrección (y comentario)
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
    ultimo_riego_fecha: dt.date | None = None
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
