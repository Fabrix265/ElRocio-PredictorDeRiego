"""Dependencias de FastAPI: sesión de BD, contexto de la petición, usuario autenticado y roles.

- :func:`usuario_actual` valida el access token (JWT) y carga el usuario **de la BD** en cada
  petición: si está inactivo o su ``token_version`` cambió (desactivado, cambio de rol o de
  contraseña), el token deja de servir al instante.
- :func:`usuario_habilitado` además bloquea con 403 a quien debe cambiar su contraseña; solo
  ``/auth/me``, ``/auth/cambiar-password`` y ``/auth/logout`` quedan disponibles.
- :func:`requiere_rol` arma la dependencia de permisos de cada endpoint.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Annotated

import jwt
from fastapi import Depends, Path, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import NoAutenticado, SinPermiso
from app.core.security import decodificar_access_token
from app.db.session import get_db
from app.models import Usuario
from app.models.enums import RolUsuario
from app.repositories import usuarios as repo_usuarios
from app.services.contexto import ContextoPeticion

MENSAJE_DEBE_CAMBIAR = "Debes cambiar tu contraseña"
MENSAJE_SOLICITUD_NO_PERMITIDA = "Solicitud no permitida"

_bearer = HTTPBearer(auto_error=False)



def unidad_de_trabajo(db: Annotated[Session, Depends(get_db)]) -> Iterator[Session]:
    """Unidad de trabajo de cada petición: los servicios hacen ``flush`` y aquí se hace ``commit``
    si el endpoint termina sin error (``rollback`` si lanza una excepción).

    Con ``scope="function"`` el commit ocurre **antes** de enviar la respuesta: si falla, el
    cliente recibe el error y nunca ve como hecho algo que no quedó guardado.
    """
    try:
        yield db
    except BaseException:
        db.rollback()
        raise
    else:
        db.commit()


DbSesion = Annotated[Session, Depends(unidad_de_trabajo, scope="function")]

# --- Parámetros acotados ------------------------------------------------------
# Los enteros sin tope desbordan bigint en Postgres (500). Usar estos tipos en todos los IDs y
# paginaciones (también en F2–F5): fuera de rango responden 422.
MAX_ID_BD = 2**63 - 1  # bigint
MAX_PAGINA = 100_000

IdPath = Annotated[int, Path(ge=1, le=MAX_ID_BD, description="ID (entero positivo)")]
IdQuery = Annotated[int | None, Query(ge=1, le=MAX_ID_BD, description="ID (entero positivo)")]
Pagina = Annotated[int, Query(ge=1, le=MAX_PAGINA, description="Página, desde 1")]


def contexto_peticion(request: Request) -> ContextoPeticion:
    """IP y user agent. La IP es la del socket: uvicorn la reemplaza por la de
    ``X-Forwarded-For`` solo si la conexión viene de ``--forwarded-allow-ips`` (TRUSTED_PROXIES).
    Nunca se lee ``X-Forwarded-For`` directamente."""
    ip = request.client.host if request.client else None
    return ContextoPeticion.crear(ip, request.headers.get("user-agent"))


Contexto = Annotated[ContextoPeticion, Depends(contexto_peticion)]


def usuario_actual(
    db: DbSesion,
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Usuario:
    if credenciales is None or credenciales.scheme.lower() != "bearer":
        raise NoAutenticado()
    try:
        claims = decodificar_access_token(credenciales.credentials)
    except jwt.InvalidTokenError:
        raise NoAutenticado() from None
    usuario = repo_usuarios.por_id(db, int(claims["sub"]))
    if usuario is None or not usuario.activo or usuario.token_version != claims["ver"]:
        raise NoAutenticado()
    return usuario


UsuarioActual = Annotated[Usuario, Depends(usuario_actual)]


def usuario_habilitado(usuario: UsuarioActual) -> Usuario:
    if usuario.debe_cambiar_password:
        raise SinPermiso(MENSAJE_DEBE_CAMBIAR)
    return usuario


UsuarioHabilitado = Annotated[Usuario, Depends(usuario_habilitado)]


def requiere_rol(*roles: RolUsuario) -> Callable[[Usuario], Usuario]:
    """Dependencia que deja pasar solo a los roles indicados (leídos de la BD en cada petición)."""
    permitidos = frozenset(roles)

    def _verificar(usuario: UsuarioHabilitado) -> Usuario:
        if usuario.rol not in permitidos:
            raise SinPermiso()
        return usuario

    return _verificar


def _origenes_permitidos() -> set[str]:
    return {o.rstrip("/") for o in settings.cors_origin_list} | {settings.frontend_url.rstrip("/")}


def verificar_origen(request: Request) -> None:
    """Si viene ``Origin``, debe ser el del frontend (defensa CSRF de las rutas con cookie)."""
    origen = request.headers.get("origin")
    if origen is not None and origen.rstrip("/") not in _origenes_permitidos():
        raise SinPermiso(MENSAJE_SOLICITUD_NO_PERMITIDA)


def verificar_peticion_cookie(request: Request) -> None:
    """Refresh y logout: exigen ``X-Requested-With: fetch`` (no la puede poner un formulario
    de otro sitio sin un preflight CORS) y validan ``Origin``."""
    if request.headers.get("x-requested-with", "").strip().lower() != "fetch":
        raise SinPermiso(MENSAJE_SOLICITUD_NO_PERMITIDA)
    verificar_origen(request)
