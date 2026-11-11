"""Autenticación (§7): login, refresh rotativo, logout, recuperación y cambio de contraseña.

El refresh token viaja solo en la cookie ``rt`` (HttpOnly, SameSite, Path=/api/v1/auth); el
access token va en el cuerpo y el frontend lo guarda en memoria.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status
from fastapi.responses import JSONResponse

from app.api.deps import (
    Contexto,
    DbSesion,
    UsuarioActual,
    verificar_origen,
    verificar_peticion_cookie,
)
from app.core.config import settings
from app.core.errores import NoAutenticado
from app.schemas.auth import (
    CambiarPasswordEntrada,
    LoginEntrada,
    Mensaje,
    RecuperarEntrada,
    RestablecerEntrada,
    SesionSalida,
)
from app.schemas.usuarios import UsuarioSalida
from app.services import auth_service
from app.services.auth_service import SesionEmitida

router = APIRouter(prefix="/auth")

COOKIE_REFRESH = "rt"
MENSAJE_RECUPERAR = "Si el usuario existe, enviaremos un enlace a su correo."

CookieRefresh = Annotated[str | None, Cookie(alias=COOKIE_REFRESH)]


def _ruta_cookie() -> str:
    return f"{settings.api_v1_prefix.rstrip('/')}/auth"


def _poner_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_REFRESH,
        token,
        max_age=settings.refresh_token_days * 24 * 3600,
        path=_ruta_cookie(),
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _borrar_cookie(response: Response) -> None:
    response.delete_cookie(
        COOKIE_REFRESH,
        path=_ruta_cookie(),
        secure=settings.cookie_secure,
        httponly=True,
        samesite=settings.cookie_samesite,
    )


def _respuesta_sesion(response: Response, sesion: SesionEmitida) -> SesionSalida:
    _poner_cookie(response, sesion.refresh_token)
    return SesionSalida(
        access_token=sesion.access_token,
        expires_in=sesion.expires_in,
        usuario=UsuarioSalida.model_validate(sesion.usuario),
    )


@router.post("/login", response_model=SesionSalida, dependencies=[Depends(verificar_origen)])
def login(datos: LoginEntrada, response: Response, db: DbSesion, contexto: Contexto) -> SesionSalida:
    sesion = auth_service.login(db, datos.username, datos.password, contexto)
    return _respuesta_sesion(response, sesion)


@router.post(
    "/refresh",
    response_model=SesionSalida,
    responses={401: {"model": Mensaje}},
    dependencies=[Depends(verificar_peticion_cookie)],
)
def refresh(
    response: Response, db: DbSesion, contexto: Contexto, rt: CookieRefresh = None
) -> SesionSalida | JSONResponse:
    try:
        sesion = auth_service.refrescar(db, rt, contexto)
    except NoAutenticado as error:
        # La cookie ya no sirve: se borra para que el navegador no la siga enviando.
        respuesta = JSONResponse(
            {"detail": error.detail}, status_code=error.status_code, headers=error.headers
        )
        _borrar_cookie(respuesta)
        return respuesta
    return _respuesta_sesion(response, sesion)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(verificar_peticion_cookie)],
)
def logout(db: DbSesion, contexto: Contexto, rt: CookieRefresh = None) -> Response:
    auth_service.logout(db, rt, contexto)
    respuesta = Response(status_code=status.HTTP_204_NO_CONTENT)
    _borrar_cookie(respuesta)
    return respuesta


@router.post("/recuperar", status_code=status.HTTP_202_ACCEPTED, response_model=Mensaje)
def recuperar(datos: RecuperarEntrada, db: DbSesion, contexto: Contexto) -> Mensaje:
    auth_service.solicitar_recuperacion(db, datos.identificador, contexto)
    return Mensaje(detail=MENSAJE_RECUPERAR)


@router.post("/restablecer", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def restablecer(datos: RestablecerEntrada, db: DbSesion, contexto: Contexto) -> Response:
    auth_service.restablecer(db, datos.token, datos.password, contexto)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UsuarioSalida)
def me(usuario: UsuarioActual) -> UsuarioSalida:
    return UsuarioSalida.model_validate(usuario)


@router.post("/cambiar-password", response_model=SesionSalida)
def cambiar_password(
    datos: CambiarPasswordEntrada,
    response: Response,
    usuario: UsuarioActual,
    db: DbSesion,
    contexto: Contexto,
) -> SesionSalida:
    sesion = auth_service.cambiar_password(
        db, usuario, datos.password_actual, datos.password_nueva, contexto
    )
    return _respuesta_sesion(response, sesion)
