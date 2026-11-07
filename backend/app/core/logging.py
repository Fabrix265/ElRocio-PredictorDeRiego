"""Configuración de logs con redacción de secretos.

El filtro :class:`FiltroRedaccion` se instala en los *handlers* (raíz, uvicorn y APScheduler) y
reemplaza por ``[REDACTADO]`` contraseñas, tokens, cabeceras ``Authorization``/``X-Api-Secret``/
``X-Api-Key``/``Cookie``, el parámetro ``api-key=`` de WeatherLink, cualquier clave con nombre
sensible aunque tenga prefijo o sufijo (``phytech_api_secret=``, ``secret_key:``, ``token_hash``)
y cualquier texto con forma de JWT. httpx y httpcore quedan en WARNING (en INFO registran URLs completas, con la query).
"""

from __future__ import annotations

import logging
import re
import sys

REDACTADO = "[REDACTADO]"

# Nombres de clave sensibles, también con prefijo o sufijo (phytech_api_secret, secret_key,
# token_hash, api-signature, password_nueva...). "rt" es la cookie del refresh token.
_PALABRAS = r"password|passwd|contrase(?:ñ|n)a|secret|token|api[_-]?key|signature"
_CLAVES = rf"[\w-]*(?:{_PALABRAS})[\w-]*|rt"


def _redactar_valor(coincidencia: re.Match[str]) -> str:
    comilla = coincidencia.group("comilla") or ""
    return f"{coincidencia.group('clave')}{coincidencia.group('sep')}{comilla}{REDACTADO}{comilla}"


_PATRONES: list[tuple[re.Pattern[str], object]] = [
    # Cabeceras HTTP: "Authorization: Bearer xxx", "X-Api-Secret: xxx", "Cookie: rt=xxx"
    (
        re.compile(
            r"(?i)\b(authorization|proxy-authorization|x-api-secret(?:-key)?|x-api-key|set-cookie|cookie)"
            r"(['\"]?\s*[:=]\s*)(['\"]?)[^'\"\r\n,}]+"
        ),
        rf"\1\2\3{REDACTADO}",
    ),
    # Pares clave/valor estilo JSON o repr: "password": "xxx" / 'token_hash': 'xxx'
    (
        re.compile(rf"(?i)(['\"](?:{_CLAVES})['\"]\s*:\s*)(['\"])(?:\\.|(?!\2).)*\2"),
        rf"\1\2{REDACTADO}\2",
    ),
    # Clave sin comillas con "=" o ":" (query string, formularios, kwargs, settings):
    # api-key=xxx, password=xxx, #token=xxx, phytech_api_secret="xxx", api_key: xxx
    (
        re.compile(
            rf"(?i)(?<![\w-])(?P<clave>{_CLAVES})(?P<sep>\s*[:=]\s*)(?!\[REDACTADO\])"
            r"(?:(?P<comilla>['\"])(?:\\.|(?!(?P=comilla)).)*(?P=comilla)|[^&\s'\",;)}\]]+)"
        ),
        _redactar_valor,
    ),
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
