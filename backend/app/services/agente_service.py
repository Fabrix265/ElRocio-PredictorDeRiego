"""Tokens de servicio del agente del copiloto (n8n).

- El token se genera aquí y se muestra **una sola vez** (CLI ``crear-token-agente``); en la BD
  solo queda su SHA-256 y un prefijo para reconocerlo.
- Viaja en la cabecera ``X-Token-Agente`` (n8n: credencial «Header Auth»). Un token revocado o
  desconocido responde 401, igual que un JWT inválido.
- Cada uso actualiza ``ultimo_uso_at`` y queda en la auditoría (``consulta_agente``).
"""

from __future__ import annotations

import re
import secrets

from sqlalchemy.orm import Session

from app.core.errores import Conflicto, DatosInvalidos, NoEncontrado
from app.core.security import hash_token
from app.core.tiempo import ahora_utc
from app.models import TokenServicio, Usuario
from app.repositories import copiloto as repo
from app.services import auditoria_service
from app.services.contexto import SISTEMA, ContextoPeticion

PREFIJO_TOKEN = "rga_"
LARGO_PREFIJO_VISIBLE = 10
_NOMBRE_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_-]{2,59}$")


def generar_token() -> str:
    return PREFIJO_TOKEN + secrets.token_urlsafe(32)


def crear(db: Session, nombre: str, *, actor: Usuario | None = None,
          contexto: ContextoPeticion = SISTEMA) -> tuple[TokenServicio, str]:
    """Crea el token y devuelve ``(fila, token_en_claro)``. El texto en claro no se guarda."""
    nombre = nombre.strip().lower()
    if not _NOMBRE_VALIDO.match(nombre):
        raise DatosInvalidos("El nombre debe tener de 3 a 60 caracteres: minúsculas, números, «-» o «_»")
    if repo.token_por_nombre(db, nombre) is not None:
        raise Conflicto(f"Ya existe un token llamado «{nombre}»")
    token = generar_token()
    fila = TokenServicio(nombre=nombre, token_hash=hash_token(token), prefijo=token[:LARGO_PREFIJO_VISIBLE],
                         activo=True, creado_por=actor.id if actor else None)
    db.add(fila)
    db.flush()
    auditoria_service.registrar(
        db, accion=auditoria_service.TOKEN_AGENTE_CREADO, entidad=auditoria_service.ENTIDAD_TOKEN_SERVICIO,
        entidad_id=fila.id, actor=actor, actor_username=None if actor else auditoria_service.ACTOR_SISTEMA,
        detalle={"nombre": nombre, "prefijo": fila.prefijo}, contexto=contexto,
    )
    return fila, token


def revocar(db: Session, nombre: str, *, actor: Usuario | None = None,
            contexto: ContextoPeticion = SISTEMA) -> TokenServicio:
    fila = repo.token_por_nombre(db, nombre.strip())
    if fila is None:
        raise NoEncontrado(f"No existe un token llamado «{nombre}»")
    if not fila.activo:
        return fila
    fila.activo = False
    fila.revocado_at = ahora_utc()
    db.flush()
    auditoria_service.registrar(
        db, accion=auditoria_service.TOKEN_AGENTE_REVOCADO, entidad=auditoria_service.ENTIDAD_TOKEN_SERVICIO,
        entidad_id=fila.id, actor=actor, actor_username=None if actor else auditoria_service.ACTOR_SISTEMA,
        detalle={"nombre": fila.nombre, "prefijo": fila.prefijo}, contexto=contexto,
    )
    return fila


def autenticar(db: Session, token: str) -> TokenServicio | None:
    """El token activo que corresponde al texto recibido, o ``None``."""
    if not token.startswith(PREFIJO_TOKEN) or len(token) > 200:
        return None
    fila = repo.token_activo_por_hash(db, hash_token(token))
    if fila is not None:
        fila.ultimo_uso_at = ahora_utc()
    return fila


def registrar_consulta(db: Session, fila: TokenServicio, metodo: str, ruta: str,
                       contexto: ContextoPeticion) -> None:
    auditoria_service.registrar(
        db, accion=auditoria_service.CONSULTA_AGENTE, entidad=auditoria_service.ENTIDAD_TOKEN_SERVICIO,
        entidad_id=fila.id, actor_username=nombre_actor(fila), detalle={"metodo": metodo, "ruta": ruta},
        contexto=contexto,
    )


def nombre_actor(fila: TokenServicio) -> str:
    return f"agente:{fila.nombre}"[:60]
