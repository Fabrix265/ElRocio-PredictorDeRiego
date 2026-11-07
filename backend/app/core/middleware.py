"""Cabeceras de seguridad para todas las respuestas de la API (middleware ASGI puro)."""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Swagger UI (/docs, solo fuera de producción) necesita scripts y estilos externos.
_RUTAS_DOCS = ("/docs",)


class CabecerasSeguridad:
    def __init__(self, app: ASGIApp, *, hsts: bool = False) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        es_docs = scope.get("path", "").startswith(_RUTAS_DOCS)

        async def enviar(mensaje: Message) -> None:
            if mensaje["type"] == "http.response.start":
                cabeceras = MutableHeaders(scope=mensaje)
                cabeceras.setdefault("X-Content-Type-Options", "nosniff")
                cabeceras.setdefault("X-Frame-Options", "DENY")
                cabeceras.setdefault("Referrer-Policy", "no-referrer")
                if not es_docs:
                    cabeceras.setdefault(
                        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
                    )
                    # Respuestas por usuario: que ningún proxy ni navegador las guarde.
                    cabeceras.setdefault("Cache-Control", "no-store")
                if self.hsts:
                    cabeceras.setdefault(
                        "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
                    )
            await send(mensaje)

        await self.app(scope, receive, enviar)
