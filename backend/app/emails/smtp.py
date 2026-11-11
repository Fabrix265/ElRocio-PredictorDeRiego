"""Envío de correos: SMTP (con STARTTLS) o, si ``SMTP_HOST`` está vacío, archivos ``.eml``.

El modo archivo escribe en ``backend/var/correos/`` (ignorado por git) y en el log solo deja
"correo guardado en archivo" (nunca el contenido ni los enlaces).
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from app.core.config import BACKEND_ROOT, Settings, settings
from app.core.tiempo import ahora_utc

logger = logging.getLogger(__name__)

DIRECTORIO_CORREOS = BACKEND_ROOT / "var" / "correos"
REMITENTE_POR_DEFECTO = "Grupo El Rocío <no-responder@localhost>"
TIMEOUT_SMTP = 20


class Mailer(Protocol):
    def enviar(self, mensaje: EmailMessage) -> None: ...


class SmtpMailer:
    def __init__(self, config: Settings) -> None:
        self.config = config

    def enviar(self, mensaje: EmailMessage) -> None:
        c = self.config
        contexto_tls = ssl.create_default_context()
        if c.smtp_port == 465:
            servidor: smtplib.SMTP = smtplib.SMTP_SSL(
                c.smtp_host, c.smtp_port, timeout=TIMEOUT_SMTP, context=contexto_tls
            )
        else:
            servidor = smtplib.SMTP(c.smtp_host, c.smtp_port, timeout=TIMEOUT_SMTP)
        with servidor:
            servidor.ehlo()
            if c.smtp_port != 465 and c.smtp_starttls:
                servidor.starttls(context=contexto_tls)
                servidor.ehlo()
            if c.smtp_user:
                servidor.login(c.smtp_user, c.smtp_password.get_secret_value())
            servidor.send_message(mensaje)


class ArchivoMailer:
    """Guarda cada correo como ``.eml`` (desarrollo y entornos sin SMTP)."""

    def __init__(self, directorio: Path | None = None) -> None:
        self.directorio = directorio or DIRECTORIO_CORREOS

    def enviar(self, mensaje: EmailMessage) -> Path:
        self.directorio.mkdir(parents=True, exist_ok=True)
        marca = ahora_utc().strftime("%Y%m%dT%H%M%S%fZ")
        ruta = self.directorio / f"{marca}_{mensaje.get('X-Riego-Tipo', 'correo')}.eml"
        ruta.write_bytes(bytes(mensaje))
        logger.info("correo guardado en archivo (%s)", ruta.name)
        return ruta


def remitente(config: Settings | None = None) -> str:
    config = config or settings
    return config.smtp_from or REMITENTE_POR_DEFECTO


def obtener_mailer(config: Settings | None = None) -> Mailer:
    config = config or settings
    if config.smtp_host.strip():
        return SmtpMailer(config)
    return ArchivoMailer()
