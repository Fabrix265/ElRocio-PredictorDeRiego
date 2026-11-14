"""Parámetros del riego por pulsos del módulo: cualquier usuario los consulta; admin y encargado
los editan (auditado)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from app.api.deps import AdminEncargado, Contexto, DbSesion, IdPath, UsuarioHabilitado
from app.schemas.pulsos import ParametrosPulsosEntrada, ParametrosPulsosSalida
from app.services import parametros_pulsos_service as servicio

router = APIRouter()


@router.get("/modulos/{modulo_id}/parametros-pulsos", response_model=ParametrosPulsosSalida)
def obtener(modulo_id: IdPath, _usuario: UsuarioHabilitado, db: DbSesion) -> dict[str, Any]:
    return servicio.obtener(db, modulo_id)


@router.put("/modulos/{modulo_id}/parametros-pulsos", response_model=ParametrosPulsosSalida)
def actualizar(modulo_id: IdPath, datos: ParametrosPulsosEntrada, usuario: AdminEncargado, db: DbSesion,
               contexto: Contexto) -> dict[str, Any]:
    return servicio.actualizar(db, modulo_id, datos, usuario, contexto)
