"""Tareas que corre el programador. Cada una abre y cierra su propia sesión de BD."""

from __future__ import annotations

import logging

from app.db.session import nueva_sesion
from app.emails.smtp import Mailer, obtener_mailer
from app.services import auth_service, correo_service, rate_limit

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
    """Limpieza diaria: intentos de login/recuperación de más de 30 días, y sesiones de refresh y
    enlaces de recuperación vencidos, revocados o usados hace más de 30 días."""
    db = nueva_sesion()
    try:
        borrados = rate_limit.limpiar_antiguos(db)
        sesiones, enlaces = auth_service.limpiar_vencidos(db)
        db.commit()
    finally:
        db.close()
    if borrados or sesiones or enlaces:
        logger.info(
            "Limpieza: %s intento(s), %s sesión(es) y %s enlace(s) de recuperación borrados",
            borrados, sesiones, enlaces,
        )
    return borrados
