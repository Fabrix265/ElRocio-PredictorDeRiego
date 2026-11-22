"""Sugerencias del copiloto: el agente propone, un encargado o admin decide.

Aprobar una sugerencia **no ejecuta nada**: deja constancia de que alguien la atiende (p. ej.
regenerar el plan desde la app). Repetir la misma propuesta pendiente (mismo módulo, día, tipo,
turno, alerta y título) devuelve la existente en vez de duplicarla, también si llegan dos a la vez
(índice único parcial ``uq_copiloto_sugerencia_pendiente``).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errores import Conflicto, DatosInvalidos, NoEncontrado
from app.core.tiempo import ahora_utc, hoy_lima
from app.models import CopilotoSugerencia, TokenServicio, Usuario
from app.repositories import copiloto as repo
from app.repositories import reportes as repo_reportes
from app.services import agente_service, auditoria_service, copiloto_service
from app.services.contexto import ContextoPeticion

DIAS_ATRAS_MAXIMO = 30
DIAS_ADELANTE_MAXIMO = 7
LIMITE_LISTADO = 200


def crear(db: Session, datos: Any, *, token: TokenServicio, contexto: ContextoPeticion) -> tuple[CopilotoSugerencia, bool]:
    """Crea la sugerencia (o devuelve la pendiente igual). ``(fila, creada)``."""
    modulo = copiloto_service.modulo_de(db, datos.modulo_id)
    hoy = hoy_lima()
    if not hoy - dt.timedelta(days=DIAS_ATRAS_MAXIMO) <= datos.fecha <= hoy + dt.timedelta(days=DIAS_ADELANTE_MAXIMO):
        raise DatosInvalidos(f"La fecha debe estar entre {DIAS_ATRAS_MAXIMO} días atrás y {DIAS_ADELANTE_MAXIMO} adelante")
    turno_id = None
    if datos.turno_codigo:
        turno = repo.turno_por_codigo(db, modulo.id, datos.turno_codigo)
        if turno is None:
            raise DatosInvalidos(f"El turno {datos.turno_codigo} no existe en el módulo {modulo.codigo}")
        turno_id = turno.id
    titulo = datos.titulo.strip()
    clave = {"modulo_id": modulo.id, "fecha": datos.fecha, "tipo": datos.tipo, "turno_id": turno_id,
             "alerta_codigo": datos.alerta_codigo, "titulo": titulo}
    existente = repo.pendiente_igual(db, **clave)
    if existente is not None:
        return existente, False
    fila = CopilotoSugerencia(modulo_id=modulo.id, fecha=datos.fecha, turno_id=turno_id, tipo=datos.tipo,
                              alerta_codigo=datos.alerta_codigo, titulo=titulo,
                              detalle=(datos.detalle or "").strip() or None, estado="pendiente", token_id=token.id)
    try:
        with db.begin_nested():  # otra petición igual pudo insertarla entre la consulta y el INSERT
            db.add(fila)
            db.flush()
    except IntegrityError:
        existente = repo.pendiente_igual(db, **clave)
        if existente is None:
            raise
        return existente, False
    auditoria_service.registrar(
        db, accion=auditoria_service.SUGERENCIA_CREADA, entidad=auditoria_service.ENTIDAD_SUGERENCIA,
        entidad_id=fila.id, actor_username=agente_service.nombre_actor(token),
        detalle={"modulo": modulo.codigo, "fecha": fila.fecha, "tipo": fila.tipo, "titulo": fila.titulo,
                 "turno": datos.turno_codigo, "alerta": fila.alerta_codigo},
        contexto=contexto,
    )
    return fila, True


def resolver(db: Session, sugerencia_id: int, *, aprobar: bool, comentario: str | None, actor: Usuario,
             contexto: ContextoPeticion) -> CopilotoSugerencia:
    fila = repo.sugerencia(db, sugerencia_id, bloquear=True)
    if fila is None:
        raise NoEncontrado("Sugerencia no encontrada")
    if fila.estado != "pendiente":
        raise Conflicto(f"La sugerencia ya fue {fila.estado}")
    comentario = (comentario or "").strip() or None
    if not aprobar and comentario is None:
        raise DatosInvalidos("Indica por qué descartas la sugerencia")
    fila.estado = "aprobada" if aprobar else "descartada"
    fila.resuelto_por = actor.id
    fila.resuelto_at = ahora_utc()
    fila.comentario_resolucion = comentario
    db.flush()
    auditoria_service.registrar(
        db, accion=auditoria_service.SUGERENCIA_APROBADA if aprobar else auditoria_service.SUGERENCIA_DESCARTADA,
        entidad=auditoria_service.ENTIDAD_SUGERENCIA, entidad_id=fila.id, actor=actor,
        detalle={"titulo": fila.titulo, "comentario": comentario}, contexto=contexto,
    )
    return fila


def listar(db: Session, *, estado: str | None, modulo_id: int | None, limite: int = LIMITE_LISTADO) -> list[dict[str, Any]]:
    filas = repo.listar_sugerencias(db, estado=estado, modulo_id=modulo_id, limite=min(limite, LIMITE_LISTADO))
    return salidas(db, filas)


def salidas(db: Session, filas: list[CopilotoSugerencia]) -> list[dict[str, Any]]:
    modulos = repo_reportes.modulos(db)
    turnos = repo.turnos_por_id(db, {f.turno_id for f in filas if f.turno_id})
    tokens = repo.tokens_por_id(db, {f.token_id for f in filas if f.token_id})
    usuarios = repo.nombres_usuario(db, {f.resuelto_por for f in filas if f.resuelto_por})
    salida = []
    for f in filas:
        modulo = modulos.get(f.modulo_id)
        token = tokens.get(f.token_id) if f.token_id else None
        salida.append({
            "id": f.id, "modulo_id": f.modulo_id, "modulo_codigo": modulo.codigo if modulo else None,
            "fecha": f.fecha, "turno_codigo": turnos.get(f.turno_id) if f.turno_id else None,
            "tipo": f.tipo, "alerta_codigo": f.alerta_codigo, "titulo": f.titulo, "detalle": f.detalle,
            "estado": f.estado, "propuesta_por": agente_service.nombre_actor(token) if token else "agente",
            "created_at": f.created_at, "resuelto_por": usuarios.get(f.resuelto_por) if f.resuelto_por else None,
            "resuelto_at": f.resuelto_at, "comentario_resolucion": f.comentario_resolucion,
        })
    return salida
