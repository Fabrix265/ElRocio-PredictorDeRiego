"""Configuración de logs con redacción de secretos.

El filtro :class:`FiltroRedaccion` se instala en los *handlers* (raíz, uvicorn y APScheduler) y
reemplaza por ``[REDACTADO]`` contraseñas, tokens, cabeceras ``Authorization``/``X-Api-Secret``/
``X-Api-Key``/``Cookie``, el parámetro ``api-key=`` de WeatherLink y cualquier texto con forma de
JWT. httpx y httpcore quedan en WARNING (en INFO registran URLs completas, con la query).
"""

from __future__ import annotations

import logging
import re
import sys

REDACTADO = "[REDACTADO]"

_CLAVES = (
    r"password|password_[a-z]+|passwd|contrase(?:ñ|n)a|access_token|refresh_token|id_token|token|"
    r"secret|api[_-]?secret(?:[_-]key)?|api[_-]?key|client_secret|rt"
)

_PATRONES: list[tuple[re.Pattern[str], str]] = [
    # Cabeceras HTTP: "Authorization: Bearer xxx", "X-Api-Secret: xxx", "Cookie: rt=xxx"
    (
        re.compile(
            r"(?i)\b(authorization|proxy-authorization|x-api-secret(?:-key)?|x-api-key|set-cookie|cookie)"
            r"(['\"]?\s*[:=]\s*)(['\"]?)[^'\"\r\n,}]+"
        ),
        rf"\1\2\3{REDACTADO}",
    ),
    # Pares clave/valor estilo JSON o repr: "password": "xxx" / 'token': 'xxx'
    (
        re.compile(rf"(?i)(['\"](?:{_CLAVES})['\"]\s*:\s*)(['\"])(?:\\.|(?!\2).)*\2"),
        rf"\1\2{REDACTADO}\2",
    ),
    # Query string, formularios o kwargs: api-key=xxx, password=xxx, token=xxx
    (re.compile(rf"(?i)\b({_CLAVES})=([^&\s'\",;)]+)"), rf"\1={REDACTADO}"),
    # Enlaces de recuperación: #token=xxx (cubierto arriba) y Bearer suelto
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+"), f"Bearer {REDACTADO}"),
    # Cualquier JWT
    (re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]+"), REDACTADO),
]


def redactar(texto: str) -> str:
    for patron, reemplazo in _PATRONES:
        texto = patron.sub(reemplazo, texto)
    return texto


class FiltroRedaccion(logging.Filter):
    """Redacta el mensaje ya formateado (``msg % args``) y el texto de la excepción.

    Si no hay nada que ocultar, el registro queda intacto. El log de accesos de uvicorn necesita
    conservar ``args`` (su formateador los desarma: cliente, método, ruta, versión, estado), así
    que ahí se redacta argumento por argumento.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            mensaje = record.getMessage()
        except Exception:  # noqa: BLE001 - un log mal formado no debe romper la app
            mensaje = str(record.msg)
        redactado = redactar(mensaje)
        if redactado != mensaje:
            if record.name.startswith("uvicorn.access") and isinstance(record.args, tuple):
                record.args = tuple(redactar(a) if isinstance(a, str) else a for a in record.args)
            else:
                record.msg = redactado
                record.args = None
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redactar(record.exc_text)
        return True


_LOGGERS_CON_HANDLERS = ("", "uvicorn", "uvicorn.error", "uvicorn.access", "apscheduler")


def instalar_filtro() -> None:
    """Agrega el filtro a todos los handlers de la raíz, uvicorn y APScheduler (idempotente)."""
    filtro = FiltroRedaccion()
    for nombre in _LOGGERS_CON_HANDLERS:
        for handler in logging.getLogger(nombre).handlers:
            if not any(isinstance(f, FiltroRedaccion) for f in handler.filters):
                handler.addFilter(filtro)


def configurar_logging(nivel: int | str = logging.INFO) -> None:
    raiz = logging.getLogger()
    if not raiz.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        raiz.addHandler(handler)
        raiz.setLevel(nivel)
    for ruidoso in ("httpx", "httpcore"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    instalar_filtro()
