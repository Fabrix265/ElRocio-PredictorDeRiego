"""Datos de la petición que los servicios necesitan para auditar y limitar intentos."""

from __future__ import annotations

from dataclasses import dataclass

LARGO_IP = 64
LARGO_USER_AGENT = 512


@dataclass(frozen=True)
class ContextoPeticion:
    """IP real (uvicorn la toma de X-Forwarded-For solo si viene de TRUSTED_PROXIES) y user agent."""

    ip: str | None = None
    user_agent: str | None = None

    @classmethod
    def crear(cls, ip: str | None, user_agent: str | None) -> ContextoPeticion:
        return cls(
            ip=(ip or None) and ip[:LARGO_IP],
            user_agent=(user_agent or None) and user_agent[:LARGO_USER_AGENT],
        )


SISTEMA = ContextoPeticion()
