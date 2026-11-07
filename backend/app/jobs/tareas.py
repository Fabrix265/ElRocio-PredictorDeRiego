"""Tareas que corre el programador. Cada una abre y cierra su propia sesión de BD."""

from __future__ import annotations

import logging

from app.db.session import nueva_sesion
from app.emails.smtp import Mailer, obtener_mailer
from app.services import correo_service, rate_limit

logger = logging.getLogger(__name__)


def enviar_correos(mailer: Mailer | None = None) -> correo_service.ResultadoEnvio:
    """Procesa la cola ``notificacion_correo`` (lotes con ``FOR UPDATE SKIP LOCKED``)."""
    mailer = mailer or obtener_mailer()
    db = nueva_sesion()
    try:
        resultado = correo_service.procesar_pendientes(db, mailer)
    finally:
        db.close()
    if resultado.total:
        logger.info(
            "Cola de correos: %s enviado(s), %s sin destinatarios, %s a reintentar, %s con error",
            resultado.enviados, resultado.sin_destinatarios, resultado.reintentos, resultado.errores,
        )
    return resultado


def limpiar_intentos() -> int:
    """Borra los intentos de login/recuperación de más de 30 días."""
    db = nueva_sesion()
    try:
        borrados = rate_limit.limpiar_antiguos(db)
        db.commit()
    finally:
        db.close()
    if borrados:
        logger.info("Intentos de ingreso antiguos borrados: %s", borrados)
    return borrados
