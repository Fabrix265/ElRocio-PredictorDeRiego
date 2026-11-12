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

from fastapi import APIRouter, Depends, Path, Query, Response

from app.api.deps import AdminEncargado, MAX_ID_BD, Contexto, DbSesion, IdPath, UsuarioHabilitado, requiere_rol
from app.core.tiempo import hoy_lima
from app.models import Usuario
from app.models.enums import RolUsuario
from app.schemas.cronograma import (
    CronogramaDetalle,
    CronogramaListado,
    CronogramaConAvisos,
    DiferenciasSalida,
    EdicionEntrada,
    EliminarCronogramaEntrada,
    EliminarCronogramaSalida,
    EventoSalida,
    GenerarEntrada,
    GenerarSalida,
    GuardarVersionEntrada,
    MantenerEntrada,
    PublicarEntrada,
    RegenerarEntrada,
    SolicitarCorreccionEntrada,
    VersionDetalle,
    VersionPrevia,
    VersionResumen,
    VistoEntrada,
)
from app.services import cronograma_service, reportes_service
from app.services import flujo_cronograma_service as flujo

router = APIRouter(prefix="/cronogramas")

AdminProgramador = Annotated[Usuario, Depends(requiere_rol(RolUsuario.admin, RolUsuario.programador))]
AdminSubgerente = Annotated[Usuario, Depends(requiere_rol(RolUsuario.admin, RolUsuario.subgerente))]
ProgramadorSubgerente = Annotated[Usuario, Depends(requiere_rol(RolUsuario.programador, RolUsuario.subgerente))]
AdminEncargadoSubgerente = Annotated[
    Usuario, Depends(requiere_rol(RolUsuario.admin, RolUsuario.encargado, RolUsuario.subgerente))
]
TodosRoles = Annotated[Usuario, Depends(requiere_rol(*RolUsuario))]
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


@router.delete("/{cronograma_id}", response_model=EliminarCronogramaSalida)
def eliminar(cronograma_id: IdPath, datos: EliminarCronogramaEntrada, usuario: AdminEncargado,
             db: DbSesion, contexto: Contexto) -> dict:
    return flujo.eliminar(db, cronograma_id, datos.motivo, datos.lock_version, usuario, contexto)


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


@router.post("/{cronograma_id}/recalcular", response_model=VersionPrevia)
def recalcular(cronograma_id: IdPath, datos: EdicionEntrada, usuario: AdminEncargado, db: DbSesion) -> dict:
    return flujo.recalcular(db, cronograma_id, datos, usuario)


@router.get("/{cronograma_id}/alternativas", response_model=dict[int, dict[str, list[dict[str, Any]]]])
def alternativas(cronograma_id: IdPath, usuario: AdminEncargado, db: DbSesion) -> dict:
    return flujo.alternativas(db, cronograma_id, usuario)


@router.post("/{cronograma_id}/versiones", response_model=CronogramaDetalle)
def guardar_version(cronograma_id: IdPath, datos: GuardarVersionEntrada, usuario: AdminEncargado,
                    db: DbSesion, contexto: Contexto) -> dict:
    return flujo.guardar_version(db, cronograma_id, datos, usuario, contexto)


@router.delete("/{cronograma_id}/borrador", response_model=CronogramaDetalle)
def descartar_borrador(cronograma_id: IdPath, usuario: AdminEncargado, db: DbSesion, contexto: Contexto) -> dict:
    return flujo.descartar_borrador(db, cronograma_id, usuario, contexto)


@router.post("/{cronograma_id}/publicar", response_model=CronogramaConAvisos)
def publicar(cronograma_id: IdPath, datos: PublicarEntrada, usuario: AdminEncargado,
             db: DbSesion, contexto: Contexto) -> dict:
    return flujo.publicar(db, cronograma_id, datos.lock_version, usuario, contexto)


@router.post("/{cronograma_id}/visto", response_model=CronogramaConAvisos)
def visto(cronograma_id: IdPath, datos: VistoEntrada, usuario: AdminProgramador,
          db: DbSesion, contexto: Contexto) -> dict:
    return flujo.visto(db, cronograma_id, datos.version_id, usuario, contexto)


@router.post("/{cronograma_id}/vista", status_code=204, response_class=Response)
def vista(cronograma_id: IdPath, usuario: ProgramadorSubgerente, db: DbSesion, contexto: Contexto) -> Response:
    flujo.vista(db, cronograma_id, usuario, contexto)
    return Response(status_code=204)


@router.post("/{cronograma_id}/solicitar-correccion", response_model=CronogramaDetalle)
def solicitar_correccion(cronograma_id: IdPath, datos: SolicitarCorreccionEntrada, usuario: AdminSubgerente,
                         db: DbSesion, contexto: Contexto) -> dict:
    return flujo.solicitar_correccion(db, cronograma_id, datos.version_id, datos.motivo, usuario, contexto)


@router.post("/{cronograma_id}/mantener", response_model=CronogramaDetalle)
def mantener(cronograma_id: IdPath, datos: MantenerEntrada, usuario: AdminEncargado,
             db: DbSesion, contexto: Contexto) -> dict:
    return flujo.mantener(db, cronograma_id, datos.comentario, usuario, contexto)


@router.get("/{cronograma_id}/diferencias", response_model=DiferenciasSalida)
def diferencias(cronograma_id: IdPath, usuario: TodosRoles, db: DbSesion,
                 base: Annotated[int, Query(ge=1, le=100_000)],
                 contra: Annotated[int, Query(ge=1, le=100_000)]) -> dict:
    return flujo.diferencias(db, cronograma_id, base, contra, usuario)


@router.get("/{cronograma_id}/eventos", response_model=list[EventoSalida])
def eventos(cronograma_id: IdPath, usuario: AdminEncargadoSubgerente, db: DbSesion) -> list[dict]:
    return flujo.eventos(db, cronograma_id, usuario)


@router.get("/{cronograma_id}/datos-campo", response_model=list[dict[str, Any]])
def datos_campo(cronograma_id: IdPath, usuario: AdminEncargadoSubgerente, db: DbSesion,
                 dias: Annotated[int, Query(ge=1, le=14)] = 7) -> list[dict]:
    return flujo.datos_campo(db, cronograma_id, dias, usuario)


@router.get("/{cronograma_id}/exportar")
def exportar(
    cronograma_id: IdPath, usuario: UsuarioHabilitado, db: DbSesion, contexto: Contexto,
    formato: Annotated[str, Query(pattern="^(pdf|xlsx)$")] = "pdf",
) -> Response:
    """PDF o Excel de la versión visible (el programador, siempre la publicada); audita y deja el
    evento ``exportado``."""
    contenido, media, nombre = reportes_service.exportar(db, cronograma_id, formato, usuario, contexto)
    return Response(contenido, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
