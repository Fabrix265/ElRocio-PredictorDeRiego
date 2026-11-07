"""Programador de tareas (APScheduler 3, zona de Lima).

- ``enviar_correos`` cada 30 s.
- ``limpiar_intentos`` todos los días a las 03:15 (hora de Lima): intentos de ingreso, sesiones
  de refresh y enlaces de recuperación antiguos.

``coalesce`` y ``max_instances=1``: si una corrida se atrasa no se acumulan ejecuciones. Entre
procesos, la cola de correos se reparte con ``FOR UPDATE SKIP LOCKED`` (no hay candados de sesión,
compatibles con el pooler 6543).
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.tiempo import zona_lima
from app.jobs import tareas

logger = logging.getLogger(__name__)

INTERVALO_CORREOS_S = 30

JOB_DEFAULTS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600}


def configurar(programador: BaseScheduler) -> BaseScheduler:
    programador.add_job(
        tareas.enviar_correos, "interval", seconds=INTERVALO_CORREOS_S,
        id="enviar_correos", name="Enviar correos pendientes", replace_existing=True,
    )
    programador.add_job(
        tareas.limpiar_intentos, "cron", hour=3, minute=15,
        id="limpiar_intentos", name="Borrar intentos, sesiones y enlaces antiguos", replace_existing=True,
    )
    return programador


def crear_programador(*, en_segundo_plano: bool) -> BaseScheduler:
    clase = BackgroundScheduler if en_segundo_plano else BlockingScheduler
    return configurar(clase(timezone=zona_lima(), job_defaults=JOB_DEFAULTS))
