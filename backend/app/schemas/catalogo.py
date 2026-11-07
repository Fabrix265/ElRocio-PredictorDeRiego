"""Esquemas de catálogos: fundos › módulos › turnos y motivos de corrección."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TurnoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    orden: int
    area_ha: float
    valvula_controlador: str


class ModuloSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    area_ha: float
    turnos: list[TurnoSalida] = Field(default_factory=list)


class FundoSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    modulos: list[ModuloSalida] = Field(default_factory=list)


class MotivoCorreccionSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    codigo: str
    nombre: str
    orden: int
