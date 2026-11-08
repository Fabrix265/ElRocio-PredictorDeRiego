"""Ingesta de APIs (§3.6, §4 "Datos de campo, panel e ingesta").

| Ruta | Quién |
|---|---|
| ``POST /ingestas/ejecutar`` ``{fuentes?, desde?, hasta?}`` | A E |
| ``GET /ingestas?limite&fuente`` | A E S |

``POST`` crea las corridas (``en_curso``), confirma la transacción antes de responder 202 y lanza
la misma ingesta que la tarea diaria en segundo plano; el avance se consulta con ``GET``. Las
corridas nunca llevan secretos (errores con ``{tipo, status_code, endpoint sin query, mensaje
redactado}``).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from app.api.deps import DbSesion, requiere_rol
from app.models import IngestaCorrida, Usuario
from app.models.enums import RolUsuario
from app.repositories import ingestas as repo_ingestas
from app.schemas.datos import IngestaCorridaSalida, PeticionIngesta
from app.services import ingesta_service

router = APIRouter(prefix="/ingestas")

AdminEncargado = Annotated[Usuario, Depends(requiere_rol(RolUsuario.admin, RolUsuario.encargado))]
AdminEncargadoSubgerente = Annotated[
    Usuario, Depends(requiere_rol(RolUsuario.admin, RolUsuario.encargado, RolUsuario.subgerente))
]
MAX_LIMITE = 200


def corrida_salida(corrida: IngestaCorrida, username: str | None) -> IngestaCorridaSalida:
    return IngestaCorridaSalida(
        id=corrida.id, fuente=corrida.fuente, disparo=corrida.disparo.value, usuario=username,
        fecha_programada=corrida.fecha_programada, desde=corrida.desde, hasta=corrida.hasta,
        inicio_at=corrida.inicio_at, fin_at=corrida.fin_at, duracion_ms=corrida.duracion_ms,
        latido_at=corrida.latido_at,
        estado=corrida.estado.value, filas_nuevas=corrida.filas_nuevas or 0,
        filas_actualizadas=corrida.filas_actualizadas or 0, filas_omitidas=corrida.filas_omitidas or 0,
        conflictos=corrida.conflictos or 0, errores=corrida.errores or [],
    )


@router.post("/ejecutar", response_model=list[IngestaCorridaSalida], status_code=status.HTTP_202_ACCEPTED)
def ejecutar(
    peticion: PeticionIngesta,
    usuario: AdminEncargado,
    db: DbSesion,
    tareas: BackgroundTasks,
) -> list[IngestaCorridaSalida]:
    """"Actualizar ahora". Sin ``fuentes`` = todas; sin fechas, cada fuente usa su rango automático
    (última fecha guardada − 3 días hasta ayer). 409 si alguna fuente ya está en curso."""
    corridas = ingesta_service.lanzar_manual(
        db, peticion.fuentes, usuario_id=usuario.id, desde=peticion.desde, hasta=peticion.hasta
    )
    # La unidad de trabajo confirma antes de responder; la tarea corre después de la respuesta.
    tareas.add_task(ingesta_service.ejecutar_en_segundo_plano, [c.id for c in corridas])
    return [corrida_salida(c, usuario.username) for c in corridas]


@router.get("", response_model=list[IngestaCorridaSalida])
def listar(
    _usuario: AdminEncargadoSubgerente,
    db: DbSesion,
    limite: Annotated[int, Query(ge=1, le=MAX_LIMITE)] = 20,
    fuente: Annotated[str | None, Query(max_length=40)] = None,
) -> list[IngestaCorridaSalida]:
    """Las últimas ``limite`` corridas más todas las en curso, ordenadas por inicio descendente."""
    return [corrida_salida(c, u) for c, u in repo_ingestas.listar(db, limite=limite, fuente=fuente)]
