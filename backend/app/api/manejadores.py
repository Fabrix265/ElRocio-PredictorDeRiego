"""Traducción de errores a respuestas HTTP ``{"detail": ...}`` en español.

- :class:`~app.core.errores.ErrorApp` → su código y mensaje.
- Errores HTTP de Starlette (ruta inexistente, método no permitido) → mensaje en español.
- Validación (422) → lista ``[{loc, msg, type}]`` como FastAPI, con ``msg`` en español.
- Cualquier otra excepción → 500 genérico (el detalle queda solo en el log, ya redactado).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.errores import ErrorApp

logger = logging.getLogger("app.errores")

MENSAJES_HTTP = {
    400: "Solicitud no válida",
    401: "Sesión no válida o vencida",
    403: "No tienes permiso para realizar esta acción",
    404: "Recurso no encontrado",
    405: "Método no permitido",
    413: "El archivo o la solicitud es demasiado grande",
    415: "Tipo de contenido no admitido",
    500: "Error interno del servidor",
}

_MENSAJES_VALIDACION = {
    "missing": "Este campo es obligatorio.",
    "extra_forbidden": "Campo no permitido.",
    "string_type": "Debe ser un texto.",
    "string_too_short": "Debe tener al menos {min_length} caracteres.",
    "string_too_long": "Debe tener como máximo {max_length} caracteres.",
    "string_pattern_mismatch": "El formato no es válido.",
    "int_parsing": "Debe ser un número entero.",
    "int_type": "Debe ser un número entero.",
    "float_parsing": "Debe ser un número.",
    "bool_parsing": "Debe ser verdadero o falso.",
    "bool_type": "Debe ser verdadero o falso.",
    "greater_than_equal": "Debe ser mayor o igual que {ge}.",
    "less_than_equal": "Debe ser menor o igual que {le}.",
    "enum": "Valor no válido. Opciones: {expected}.",
    "literal_error": "Valor no válido. Opciones: {expected}.",
    "json_invalid": "El cuerpo no es un JSON válido.",
    "model_attributes_type": "El cuerpo debe ser un objeto JSON.",
    "dict_type": "El cuerpo debe ser un objeto JSON.",
    "date_from_datetime_parsing": "Debe ser una fecha válida (AAAA-MM-DD).",
    "date_parsing": "Debe ser una fecha válida (AAAA-MM-DD).",
    "datetime_parsing": "Debe ser una fecha y hora válida (ISO 8601).",
}


def _mensaje_validacion(error: dict) -> str:
    tipo = error.get("type", "")
    if tipo == "value_error":
        mensaje = str(error.get("msg", ""))
        mensaje = mensaje.removeprefix("Value error, ")
        if "valid email" in mensaje.lower():
            return "Ingresa un correo válido."
        return mensaje
    plantilla = _MENSAJES_VALIDACION.get(tipo)
    if plantilla is None:
        return "Valor no válido."
    ctx = {k: v for k, v in (error.get("ctx") or {}).items()}
    if "expected" in ctx:
        ctx["expected"] = str(ctx["expected"]).replace(" or ", " o ")
    try:
        return plantilla.format(**ctx)
    except (KeyError, IndexError):
        return plantilla.split("{")[0].strip() or "Valor no válido."


async def _error_app(_request: Request, error: ErrorApp) -> JSONResponse:
    return JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)


async def _error_http(_request: Request, error: StarletteHTTPException) -> JSONResponse:
    detalle = error.detail
    if not isinstance(detalle, str) or detalle in ("Not Found", "Method Not Allowed", "Unauthorized",
                                                    "Forbidden", "Bad Request", "Not authenticated"):
        detalle = MENSAJES_HTTP.get(error.status_code, detalle if isinstance(detalle, str) else "Error")
    return JSONResponse({"detail": detalle}, status_code=error.status_code,
                        headers=getattr(error, "headers", None))


async def _error_validacion(_request: Request, error: RequestValidationError) -> JSONResponse:
    errores = [
        {"loc": list(e.get("loc", ())), "msg": _mensaje_validacion(e), "type": e.get("type", "")}
        for e in error.errors()
    ]
    return JSONResponse({"detail": jsonable_encoder(errores)}, status_code=422)


async def _error_inesperado(request: Request, error: Exception) -> JSONResponse:
    logger.exception("Error no controlado en %s %s", request.method, request.url.path)
    return JSONResponse({"detail": MENSAJES_HTTP[500]}, status_code=500)


def registrar_manejadores(app: FastAPI) -> None:
    app.add_exception_handler(ErrorApp, _error_app)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _error_http)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, _error_validacion)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _error_inesperado)
