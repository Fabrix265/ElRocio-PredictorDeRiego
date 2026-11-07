"""Catálogos para cualquier usuario autenticado: fundos con módulos y turnos, y motivos."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import DbSesion, UsuarioHabilitado
from app.repositories import catalogo as repo_catalogo
from app.schemas.catalogo import FundoSalida, ModuloSalida, MotivoCorreccionSalida, TurnoSalida

router = APIRouter()


@router.get("/fundos", response_model=list[FundoSalida])
def fundos(_usuario: UsuarioHabilitado, db: DbSesion) -> list[FundoSalida]:
    """Solo lo activo, en orden (selector Fundo › Módulo de la cabecera)."""
    return [
        FundoSalida(
            id=fundo.id,
            codigo=fundo.codigo,
            nombre=fundo.nombre,
            modulos=[
                ModuloSalida(
                    id=modulo.id,
                    codigo=modulo.codigo,
                    nombre=modulo.nombre,
                    area_ha=modulo.area_ha,
                    turnos=[TurnoSalida.model_validate(t) for t in modulo.turnos if t.activo],
                )
                for modulo in fundo.modulos
                if modulo.activo
            ],
        )
        for fundo in repo_catalogo.fundos_con_modulos(db)
    ]


@router.get("/motivos-correccion", response_model=list[MotivoCorreccionSalida])
def motivos_correccion(_usuario: UsuarioHabilitado, db: DbSesion) -> list:
    return repo_catalogo.motivos_activos(db)
