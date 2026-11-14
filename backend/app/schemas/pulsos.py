"""Esquemas de los parámetros del riego por pulsos (los datos fijos de la planilla, por módulo)."""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ModoVentana = Literal["automatico_con_respaldo", "automatico", "curva_1", "curva_2", "curva_3"]


class ParametrosPulsosEntrada(BaseModel):
    """Lo que se puede editar. Las fracciones van en 0–1 (0,14 = 14 %)."""

    model_config = ConfigDict(extra="forbid")

    activo: bool
    textura_suelo: str = Field(min_length=1, max_length=30)
    capacidad_campo: float = Field(gt=0, le=1)
    punto_marchitez: float = Field(ge=0, lt=1)
    agotamiento_maximo: float = Field(gt=0, le=1)
    infiltracion_basica_mmh: float = Field(gt=0, le=1000)
    ancho_humedo_m: float = Field(gt=0, le=50)
    profundidad_raices_m: float = Field(gt=0, le=5)
    diametro_bulbo_m: float | None = Field(default=None, gt=0, le=10)
    distancia_hileras_m: float = Field(gt=0, le=50)
    distancia_plantas_m: float = Field(gt=0, le=50)
    mangueras_por_hilera: int = Field(ge=1, le=20)
    separacion_mangueras_m: float = Field(gt=0, le=10)
    distancia_goteros_m: float = Field(gt=0, le=10)
    caudal_gotero_lh: float = Field(gt=0, le=100)
    reposo_min_por_hora: float = Field(ge=0, lt=60)
    eficiencia_aplicacion: float = Field(gt=0, le=1)
    fase_fenologica: str = Field(min_length=1, max_length=40)
    agotamiento_por_fase: dict[str, float] = Field(min_length=1, max_length=20)
    agotamiento_automatico: bool
    umbral_etr_1: float = Field(gt=0, le=30)
    umbral_etr_2: float = Field(gt=0, le=30)
    modo_ventana: ModoVentana
    # "1"/"2"/"3" → hora ("3".."20") → % de la ETr aplicada en esa hora; cada curva suma 100.
    curvas: dict[str, dict[str, float]]
    ajustar_pulso_al_total: bool


class DerivadosSalida(BaseModel):
    """Lo que la planilla calcula a partir de los datos fijos (con el n° de turnos del módulo)."""

    turnos: int
    diametro_bulbo_m: float
    ancho_bulbos_m: float
    franja_continua: bool
    ancho_efectivo_m: float
    volumen_explorado_m3ha: float
    agua_util: float
    agua_disponible_m3ha: float
    capacidad_riego_m3hah: float
    intensidad_mmh: float
    plantas_ha: float
    goteros_ha: float
    agotamiento_fase: float
    agotamiento_max_bloque: float
    agotamiento_operativo: float
    amortiguacion_m3ha: float
    volumen_pulso_m3ha: float
    minutos_pulso: float


class ParametrosPulsosSalida(ParametrosPulsosEntrada):
    modulo_id: int
    guardado: bool  # False = aún no hay fila: se muestran los valores de la planilla
    actualizado_at: dt.datetime | None = None
    actualizado_por: str | None = None
    derivados: DerivadosSalida | None = None
    avisos: list[str] = Field(default_factory=list)
