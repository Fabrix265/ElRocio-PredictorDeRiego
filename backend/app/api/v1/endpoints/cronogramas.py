"""Cronogramas (§4; F3: generar, regenerar y lectura).

| Ruta | Quién |
|---|---|
| ``POST /cronogramas/generar`` | A E |
| ``GET /cronogramas?modulo_id&desde&hasta&estado`` | todos (P solo publicados) |
| ``GET /cronogramas/por-fecha?modulo_id&fecha`` | todos (P publicado) |
| ``GET /cronogramas/{id}`` | A E S; P publicado |
| ``GET /cronogramas/{id}/versiones[/{n}]`` | A E S; P solo publicadas |
| ``POST /cronogramas/{id}/regenerar`` | A E |

La generación corre el modelo (segundos): los endpoints que lo usan son síncronos (FastAPI los
ejecuta en el pool de hilos) para no bloquear el bucle de eventos.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query

from app.api.deps import MAX_ID_BD, Contexto, DbSesion, IdPath, UsuarioHabilitado, requiere_rol
from app.core.tiempo import hoy_lima
from app.models import Usuario
from app.models.enums import RolUsuario
from app.schemas.cronograma import (
    CronogramaDetalle,
    CronogramaListado,
    GenerarEntrada,
    GenerarSalida,
    RegenerarEntrada,
    VersionDetalle,
    VersionResumen,
)
from app.services import cronograma_service

router = APIRouter(prefix="/cronogramas")

AdminEncargado = Annotated[Usuario, Depends(requiere_rol(RolUsuario.admin, RolUsuario.encargado))]
ModuloQuery = Annotated[int, Query(ge=1, le=MAX_ID_BD)]


@router.post("/generar", response_model=GenerarSalida)
def generar(datos: GenerarEntrada, usuario: AdminEncargado, db: DbSesion, contexto: Contexto) -> dict[str, Any]:
    return cronograma_service.generar(
        db, modulo_id=datos.modulo_id, fecha_inicio=datos.fecha_inicio or hoy_lima(), dias=datos.dias,
        regenerar_existentes=datos.regenerar_existentes, actor=usuario, contexto=contexto,
    )


@router.get("", response_model=list[CronogramaListado])
def listar(
    usuario: UsuarioHabilitado, db: DbSesion, modulo_id: ModuloQuery,
    desde: dt.date | None = None, hasta: dt.date | None = None,
    estado: Annotated[str | None, Query(max_length=40)] = None,
) -> list[dict[str, Any]]:
    return cronograma_service.listar(db, modulo_id, desde, hasta, estado, usuario)


@router.get("/por-fecha", response_model=CronogramaDetalle | None)
def por_fecha(usuario: UsuarioHabilitado, db: DbSesion, modulo_id: ModuloQuery, fecha: dt.date) -> dict[str, Any] | None:
    return cronograma_service.por_fecha(db, modulo_id, fecha, usuario)


@router.get("/{cronograma_id}", response_model=CronogramaDetalle)
def detalle(cronograma_id: IdPath, usuario: UsuarioHabilitado, db: DbSesion) -> dict[str, Any]:
    return cronograma_service.detalle(db, cronograma_id, usuario)


@router.get("/{cronograma_id}/versiones", response_model=list[VersionResumen])
def versiones(cronograma_id: IdPath, usuario: UsuarioHabilitado, db: DbSesion) -> list[dict[str, Any]]:
    return cronograma_service.versiones(db, cronograma_id, usuario)


@router.get("/{cronograma_id}/versiones/{numero}", response_model=VersionDetalle)
def version(
    cronograma_id: IdPath, numero: Annotated[int, Path(ge=1, le=100_000)], usuario: UsuarioHabilitado, db: DbSesion,
) -> dict[str, Any]:
    return cronograma_service.version(db, cronograma_id, numero, usuario)


@router.post("/{cronograma_id}/regenerar", response_model=GenerarSalida)
def regenerar(
    cronograma_id: IdPath, usuario: AdminEncargado, db: DbSesion, contexto: Contexto,
    datos: RegenerarEntrada | None = None,
) -> dict[str, Any]:
    return cronograma_service.regenerar(
        db, cronograma_id, confirmar=bool(datos and datos.confirmar), actor=usuario, contexto=contexto
    )
