"""Copiloto agrónomo: lo que consume el agente de n8n y la vista «Copiloto» de la app.

| Ruta | Quién |
|---|---|
| ``GET /copiloto/modulos`` | agente · A · E · S |
| ``GET /copiloto/resumen?modulo_id&fecha`` | agente · A · E · S |
| ``GET /copiloto/alertas?modulo_id&fecha`` | agente · A · E · S |
| ``GET /copiloto/plan?modulo_id&fecha`` | agente · A · E · S |
| ``GET /copiloto/plan/texto?modulo_id&dia`` | agente · A · E · S |
| ``GET /copiloto/agua?modulo_id&desde&hasta&turno`` | agente · A · E · S |
| ``GET /copiloto/clima?modulo_id&desde&hasta`` | agente · A · E · S |
| ``GET /copiloto/pronostico?dias`` | agente · A · E · S |
| ``GET /copiloto/sugerencias?estado&modulo_id`` | agente · A · E · S |
| ``POST /copiloto/sugerencias`` | solo el agente |
| ``POST /copiloto/sugerencias/{id}/aprobar`` · ``/descartar`` | A · E |
| ``GET /copiloto/avisos?modulo_id&pendientes`` | agente · A · E · S |
| ``POST /copiloto/avisos/confirmar`` | solo el agente |

El agente se autentica con ``X-Token-Agente`` (token de servicio, ver ``app.services.agente_service``);
los usuarios, con su sesión. Todo es de solo lectura salvo las sugerencias y la confirmación de
avisos enviados, que nunca tocan cronogramas ni riego.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import (
    AdminEncargado,
    Contexto,
    DbSesion,
    IdPath,
    IdQuery,
    lector_copiloto,
    solo_agente,
)
from app.core.tiempo import ahora_lima, hoy_lima
from app.models import TokenServicio
from app.repositories import copiloto as repo
from app.repositories import riego as repo_riego
from app.schemas.copiloto import (
    ConfirmarAvisosEntrada,
    EstadoSugerencia,
    ResolverEntrada,
    SugerenciaCreada,
    SugerenciaEntrada,
    SugerenciaSalida,
)
from app.services import avisos_service, copiloto_service, sugerencia_service
from app.services.copiloto_service import Lector

router = APIRouter(prefix="/copiloto")

LectorCopiloto = Annotated[Lector, Depends(lector_copiloto)]
Agente = Annotated[TokenServicio, Depends(solo_agente)]
Fecha = Annotated[dt.date | None, Query(description="AAAA-MM-DD (por defecto hoy, hora de Lima)")]


@router.get("/modulos")
def modulos(_lector: LectorCopiloto, db: DbSesion) -> list[dict[str, Any]]:
    """Módulos activos con sus turnos (para que el agente sepa qué puede consultar)."""
    return [
        {"id": m.id, "codigo": m.codigo, "nombre": m.nombre, "area_ha": round(m.area_ha, 2),
         "turnos": [{"codigo": t.codigo, "area_ha": round(t.area_ha, 2)}
                    for t in repo_riego.turnos_de_modulo(db, m.id) if t.activo]}
        for m in repo.modulos_activos(db)
    ]


@router.get("/resumen")
def resumen(lector: LectorCopiloto, db: DbSesion, modulo_id: IdQuery = None, fecha: Fecha = None) -> dict[str, Any]:
    """Informe del día: plan de hoy y mañana, agua de ayer, contexto, pronóstico y alertas."""
    return copiloto_service.resumen(db, copiloto_service.modulo_de(db, modulo_id), fecha, lector)


@router.get("/alertas")
def alertas(lector: LectorCopiloto, db: DbSesion, modulo_id: IdQuery = None, fecha: Fecha = None) -> list[dict[str, Any]]:
    return copiloto_service.alertas(db, copiloto_service.modulo_de(db, modulo_id), fecha, lector)


@router.get("/plan")
def plan(_lector: LectorCopiloto, db: DbSesion, modulo_id: IdQuery = None, fecha: Fecha = None) -> dict[str, Any] | None:
    """Plan de un día por turno (publicado o, si no hay, el borrador). ``null`` si no se generó."""
    copiloto_service.datos_service.validar_fechas(fecha)
    return copiloto_service.plan_del_dia(db, copiloto_service.modulo_de(db, modulo_id), fecha or hoy_lima())


@router.get("/plan/texto")
def plan_texto(
    _lector: LectorCopiloto,
    db: DbSesion,
    modulo_id: IdQuery = None,
    dia: Annotated[str, Query(max_length=20, pattern=r"^[\w ./-]*$",
                              description="hoy, mañana, un día de la semana, 23/11 o 2026-11-23")] = "hoy",
) -> dict[str, Any]:
    """El plan completo de un día como texto listo para Telegram (comando ``/plan`` del bot)."""
    return avisos_service.plan_en_texto(db, copiloto_service.modulo_de(db, modulo_id), dia)


@router.get("/agua")
def agua(
    lector: LectorCopiloto,
    db: DbSesion,
    modulo_id: IdQuery = None,
    desde: Fecha = None,
    hasta: Fecha = None,
    turno: Annotated[str | None, Query(max_length=10, pattern=r"^[A-Za-z0-9-]+$", description="p. ej. TE03")] = None,
) -> dict[str, Any]:
    """Agua aplicada vs propuesta por día y turno, con totales (por defecto los últimos 14 días)."""
    return copiloto_service.agua(db, copiloto_service.modulo_de(db, modulo_id), desde, hasta, lector, turno)


@router.get("/clima")
def clima(_lector: LectorCopiloto, db: DbSesion, modulo_id: IdQuery = None, desde: Fecha = None,
          hasta: Fecha = None) -> dict[str, Any]:
    """Clima, MDS y humedad del suelo por día (por defecto los últimos 7 días) y pronóstico."""
    return copiloto_service.clima(db, copiloto_service.modulo_de(db, modulo_id), desde, hasta)


@router.get("/pronostico")
def pronostico(_lector: LectorCopiloto, db: DbSesion,
               dias: Annotated[int, Query(ge=1, le=10)] = copiloto_service.DIAS_PRONOSTICO) -> dict[str, Any]:
    """Pronóstico de Phytech (última captura) desde hoy."""
    return copiloto_service.pronostico(db, hoy_lima(), dias)


@router.get("/sugerencias", response_model=list[SugerenciaSalida])
def sugerencias(_lector: LectorCopiloto, db: DbSesion, estado: EstadoSugerencia | None = None,
                modulo_id: IdQuery = None) -> list[dict[str, Any]]:
    return sugerencia_service.listar(db, estado=estado, modulo_id=modulo_id)


@router.post("/sugerencias", response_model=SugerenciaCreada, status_code=status.HTTP_201_CREATED)
def crear_sugerencia(datos: SugerenciaEntrada, token: Agente, db: DbSesion, contexto: Contexto,
                     response: Response) -> dict[str, Any]:
    """El agente propone una acción; queda pendiente hasta que un encargado o admin decida."""
    fila, creada = sugerencia_service.crear(db, datos, token=token, contexto=contexto)
    if not creada:
        response.status_code = status.HTTP_200_OK
    return {**sugerencia_service.salidas(db, [fila])[0], "duplicada": not creada}


@router.post("/sugerencias/{sugerencia_id}/aprobar", response_model=SugerenciaSalida)
def aprobar(sugerencia_id: IdPath, usuario: AdminEncargado, db: DbSesion, contexto: Contexto,
            datos: ResolverEntrada | None = None) -> dict[str, Any]:
    fila = sugerencia_service.resolver(db, sugerencia_id, aprobar=True, comentario=datos.comentario if datos else None,
                                       actor=usuario, contexto=contexto)
    return sugerencia_service.salidas(db, [fila])[0]


@router.post("/sugerencias/{sugerencia_id}/descartar", response_model=SugerenciaSalida)
def descartar(sugerencia_id: IdPath, datos: ResolverEntrada, usuario: AdminEncargado, db: DbSesion,
              contexto: Contexto) -> dict[str, Any]:
    fila = sugerencia_service.resolver(db, sugerencia_id, aprobar=False, comentario=datos.comentario,
                                       actor=usuario, contexto=contexto)
    return sugerencia_service.salidas(db, [fila])[0]


@router.get("/avisos")
def avisos(_lector: LectorCopiloto, db: DbSesion, modulo_id: IdQuery = None,
           pendientes: Annotated[bool, Query(description="Solo los que aún no se mandaron")] = False) -> dict[str, Any]:
    """Avisos para mandar apenas pasan: el MDS cambia de nivel, la ingesta programada falló o el
    suelo no respondió al riego. Cada uno trae ``enviado`` (si n8n ya confirmó su envío)."""
    modulo = copiloto_service.modulo_de(db, modulo_id)
    lista = avisos_service.avisos(db, modulo)
    if pendientes:
        lista = [a for a in lista if not a["enviado"]]
    return {"modulo": {"id": modulo.id, "codigo": modulo.codigo, "nombre": modulo.nombre},
            "generado_at": ahora_lima().isoformat(timespec="seconds"), "avisos": lista}


@router.post("/avisos/confirmar")
def confirmar_avisos(datos: ConfirmarAvisosEntrada, token: Agente, db: DbSesion, contexto: Contexto) -> dict[str, int]:
    """n8n confirma los avisos que ya mandó por Telegram: no vuelven a salir como pendientes."""
    return avisos_service.confirmar(db, datos.claves, token=token, contexto=contexto)
