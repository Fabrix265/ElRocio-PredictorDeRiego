"""Arranque de la API: ``python -m app`` (desde ``backend/``). Es el comando de producción.

Pasa a uvicorn la configuración de ``backend/.env`` (no hace falta exportar variables en la
shell): un solo worker, cabeceras del proxy aceptadas solo desde TRUSTED_PROXIES (IP real del
cliente para los límites de intentos y la auditoría) y sin cabecera ``Server``. HOST y PORT se
leen del entorno (por defecto 0.0.0.0:8000; muchos PaaS definen PORT).
"""

from __future__ import annotations

import logging
import os

import uvicorn

from app.core.config import settings
from app.core.logging import configurar_logging

logger = logging.getLogger("app")

PROXY_POR_DEFECTO = "127.0.0.1"


def opciones_uvicorn() -> dict:
    return {
        "host": os.environ.get("HOST", "0.0.0.0"),
        "port": int(os.environ.get("PORT", "8000")),
        "workers": 1,
        "proxy_headers": True,
        "forwarded_allow_ips": settings.trusted_proxies,
        "server_header": False,
    }


def main() -> None:
    configurar_logging()
    if settings.es_produccion and settings.trusted_proxies.strip() == PROXY_POR_DEFECTO:
        logger.warning(
            "TRUSTED_PROXIES quedó en %s: detrás del proxy del hosting todos los clientes tendrían "
            "la IP del proxy (el límite por IP sería global y la auditoría guardaría esa IP). "
            "Configura la IP o red del proxy.", PROXY_POR_DEFECTO,
        )
    uvicorn.run("app.main:app", **opciones_uvicorn())


if __name__ == "__main__":
    main()
