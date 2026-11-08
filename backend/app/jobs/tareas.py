"""Tareas que corre el programador. Cada una abre y cierra su propia sesión de BD (unidad de
trabajo: commit al terminar sin error)."""

from __future__ import annotations

import logging

from app.db.session import nueva_sesion, unidad_de_trabajo
from app.emails.smtp import Mailer, obtener_mailer
from app.core.tiempo import hoy_lima
from app.services import auth_service, correo_service, ingesta_service, rate_limit

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
    with unidad_de_trabajo() as db:
        borrados = rate_limit.limpiar_antiguos(db)
        sesiones, enlaces = auth_service.limpiar_vencidos(db)
    if borrados or sesiones or enlaces:
        logger.info(
            "Limpieza: %s intento(s), %s sesión(es) y %s enlace(s) de recuperación borrados",
            borrados, sesiones, enlaces,
        )
    return borrados


def ingesta_diaria() -> list[int]:
    """Ingesta diaria de las APIs (§3.6) a ``INGESTA_HORA``. Reclama la corrida programada de hoy
    de cada fuente (``uq(fuente, fecha_programada)``: si otro proceso ya la tomó, se omite) y
    ejecuta cada una en su propia transacción. Devuelve los ids ejecutados por este proceso."""
    with unidad_de_trabajo() as db:
        colgadas = ingesta_service.cerrar_colgadas(db)
        ids = ingesta_service.reclamar_programadas(db, hoy_lima())
    if colgadas:
        logger.warning("Ingesta: %s corrida(s) sin terminar marcadas como error", colgadas)
    if not ids:
        logger.info("Ingesta diaria: otro proceso ya tomó las corridas de hoy")
        return []
    corridas = ingesta_service.ejecutar_en_sesiones(ids)
    resumen = ", ".join(f"{c.fuente} {c.estado.value}" for c in corridas)
    logger.info("Ingesta diaria terminada: %s", resumen or "sin corridas")
    return ids
