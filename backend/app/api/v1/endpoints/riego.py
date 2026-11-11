"""Riego aplicado y carga de Excel (§3.5, §4 "Riego aplicado").

| Ruta | Quién |
|---|---|
| ``GET /riego?modulo_id&desde&hasta`` | todos |
| ``GET /riego/{turno_id}/{fecha}/versiones`` | A E S |
| ``POST /riego/cargas`` (multipart: ``archivo``, ``modulo_id``) | A E |
| ``GET/PATCH /riego/cargas/{id}``, ``POST …/confirmar``, ``POST …/descartar`` | A E |
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Request, status
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile

from app.api.deps import MAX_ID_BD, Contexto, DbSesion, IdPath, UsuarioHabilitado, requiere_rol
from app.core.config import settings
from app.core.errores import DatosInvalidos
from app.models import Usuario
from app.models.enums import RolUsuario
from app.schemas.riego import CargaMarcadaSalida, CargaMarcar, CargaRiegoSalida, RiegoListado, VersionRiegoSalida
from app.schemas.riego import RegistroRiegoEntrada, RegistroRiegoSalida
from app.services import archivo_excel, carga_riego_service, riego_service

router = APIRouter(prefix="/riego")

AdminEncargadoSubgerente = Annotated[
    Usuario, Depends(requiere_rol(RolUsuario.admin, RolUsuario.encargado, RolUsuario.subgerente))
]
AdminEncargado = Annotated[Usuario, Depends(requiere_rol(RolUsuario.admin, RolUsuario.encargado))]

# Margen del multipart (cabeceras y campo modulo_id) sobre el tamaño máximo del archivo.
MARGEN_MULTIPART = 64 * 1024

_ESQUEMA_SUBIDA = {
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["archivo", "modulo_id"],
                    "properties": {
                        "archivo": {"type": "string", "format": "binary",
                                    "description": "Excel .xlsx con la hoja MOD5 (≤ 15 MB)"},
                        "modulo_id": {"type": "integer", "minimum": 1},
                    },
                }
            }
        },
    }
}


@router.get("", response_model=RiegoListado)
def listar(
    _usuario: UsuarioHabilitado,
    db: DbSesion,
    modulo_id: Annotated[int, Query(ge=1, le=MAX_ID_BD)],
    desde: dt.date | None = None,
    hasta: Annotated[dt.date | None, Query(description="Inclusivo")] = None,
) -> dict[str, Any]:
    return riego_service.listar(db, modulo_id, desde, hasta)


@router.get("/{turno_id}/{fecha}/versiones", response_model=list[VersionRiegoSalida])
def versiones(
    turno_id: IdPath,
    fecha: Annotated[dt.date, Path(description="AAAA-MM-DD")],
    _usuario: AdminEncargadoSubgerente,
    db: DbSesion,
) -> list[dict[str, Any]]:
    return riego_service.versiones(db, turno_id, fecha)


@router.post("/registros", response_model=RegistroRiegoSalida, status_code=status.HTTP_201_CREATED)
def guardar_registro(datos: RegistroRiegoEntrada, usuario: AdminEncargadoSubgerente,
                     db: DbSesion, contexto: Contexto) -> dict[str, Any]:
    return riego_service.guardar_manual(db, datos, usuario, contexto)


def _modulo_id(valor: Any) -> int:
    try:
        numero = int(str(valor).strip())
    except (TypeError, ValueError):
        numero = 0
    if not 1 <= numero <= MAX_ID_BD:
        raise DatosInvalidos("Indica el módulo (modulo_id) como un entero positivo.")
    return numero


@router.post(
    "/cargas", response_model=CargaRiegoSalida, status_code=status.HTTP_201_CREATED,
    openapi_extra=_ESQUEMA_SUBIDA,
)
async def subir_carga(
    request: Request, usuario: AdminEncargado, db: DbSesion, contexto: Contexto
) -> dict[str, Any]:
    """Sube el Excel y devuelve la vista previa (nada se aplica hasta confirmar).

    El cuerpo se lee a mano (sin ``File``/``Form``) para rechazar por ``Content-Length`` antes de
    recibir un archivo enorme y para leer el archivo con tope de tamaño."""
    largo = request.headers.get("content-length")
    if largo is None or not largo.isdigit():
        raise archivo_excel.ArchivoDemasiadoGrande("Falta el tamaño de la solicitud (Content-Length).")
    if int(largo) > archivo_excel.max_bytes() + MARGEN_MULTIPART:
        raise archivo_excel.ArchivoDemasiadoGrande(
            f"El archivo supera el máximo de {settings.upload_max_mb} MB."
        )
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise DatosInvalidos("Envía el archivo como multipart/form-data (campos archivo y modulo_id).")
    async with request.form(max_files=1, max_fields=5) as formulario:
        archivo = formulario.get("archivo")
        if not isinstance(archivo, UploadFile):
            raise DatosInvalidos("Falta el archivo (campo archivo).")
        modulo_id = _modulo_id(formulario.get("modulo_id"))
        contenido = await run_in_threadpool(archivo_excel.leer_limitado, archivo.file)
        nombre = archivo.filename
    validado = await run_in_threadpool(
        archivo_excel.validar_xlsx, nombre, contenido, hoja=carga_riego_service.HOJA
    )

    def _crear() -> dict[str, Any]:
        carga = carga_riego_service.crear_carga(
            db, modulo_id=modulo_id, archivo=validado, actor=usuario, contexto=contexto
        )
        return carga_riego_service.detalle(db, carga)

    return await run_in_threadpool(_crear)


@router.get("/cargas/{carga_id}", response_model=CargaRiegoSalida)
def obtener_carga(carga_id: IdPath, _usuario: AdminEncargado, db: DbSesion) -> dict[str, Any]:
    return carga_riego_service.detalle(db, carga_riego_service.obtener(db, carga_id))


@router.patch("/cargas/{carga_id}", response_model=CargaMarcadaSalida)
def marcar_grupos(
    carga_id: IdPath, datos: CargaMarcar, _usuario: AdminEncargado, db: DbSesion
) -> dict[str, Any]:
    return carga_riego_service.marcar(db, carga_id, [(g.id, g.aplicar) for g in datos.grupos])


@router.post("/cargas/{carga_id}/confirmar", response_model=CargaRiegoSalida)
def confirmar_carga(
    carga_id: IdPath, usuario: AdminEncargado, db: DbSesion, contexto: Contexto
) -> dict[str, Any]:
    carga = carga_riego_service.confirmar(db, carga_id, actor=usuario, contexto=contexto)
    return carga_riego_service.detalle(db, carga)


@router.post("/cargas/{carga_id}/descartar", response_model=CargaRiegoSalida)
def descartar_carga(
    carga_id: IdPath, usuario: AdminEncargado, db: DbSesion, contexto: Contexto
) -> dict[str, Any]:
    carga = carga_riego_service.descartar(db, carga_id, actor=usuario, contexto=contexto)
    return carga_riego_service.detalle(db, carga)
