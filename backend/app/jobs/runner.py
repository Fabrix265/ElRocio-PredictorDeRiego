"""Programador de tareas (APScheduler 3, zona de Lima).

- ``enviar_correos`` cada 30 s.
- ``limpiar_intentos`` todos los días a las 03:15 (hora de Lima): intentos de ingreso, sesiones
  de refresh y enlaces de recuperación antiguos.
- ``ingesta_diaria`` todos los días a ``INGESTA_HORA`` (05:00 Lima). Al arrancar, si ya pasó esa
  hora, se lanza una vez: las corridas de hoy que ya existen (ok, parcial o en curso) se omiten y
  las que terminaron en error se repiten (§8).
- ``vigilar_ingestas`` cada 5 min: cierra las corridas en curso sin latido (proceso muerto) y, ya
  pasada ``INGESTA_HORA``, repite las programadas de hoy que quedaron interrumpidas.

``coalesce`` y ``max_instances=1``: si una corrida se atrasa no se acumulan ejecuciones. Entre
procesos, la cola de correos se reparte con ``FOR UPDATE SKIP LOCKED`` y la ingesta con la fila única
``ingesta_corrida(fuente, fecha_programada)`` (no hay candados de sesión, incompatibles con el
pooler 6543).
"""

from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler

from app.core.config import settings
from app.core.tiempo import zona_lima
from app.jobs import tareas

logger = logging.getLogger(__name__)

INTERVALO_CORREOS_S = 30
INTERVALO_VIGILANCIA_S = 300

JOB_DEFAULTS = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600}
ESPERA_ARRANQUE_S = 30


def hora_ingesta() -> tuple[int, int]:
    hora, minuto = settings.ingesta_hora.split(":")
    return int(hora), int(minuto)


def ingesta_al_arrancar(ahora: dt.datetime) -> dt.datetime | None:
    """Cuándo lanzar la ingesta al arrancar (``ahora`` en hora de Lima): poco después si ya pasó
    ``INGESTA_HORA`` de hoy; ``None`` si todavía no (la lanza el cron)."""
    hora, minuto = hora_ingesta()
    if (ahora.hour, ahora.minute) < (hora, minuto):
        return None
    return ahora + dt.timedelta(seconds=ESPERA_ARRANQUE_S)


def _vigilar() -> list[int]:
    ahora = dt.datetime.now(zona_lima())
    return tareas.vigilar_ingestas(ya_es_hora=(ahora.hour, ahora.minute) >= hora_ingesta())


def configurar(programador: BaseScheduler, *, ahora: dt.datetime | None = None) -> BaseScheduler:
    programador.add_job(
        tareas.enviar_correos, "interval", seconds=INTERVALO_CORREOS_S,
        id="enviar_correos", name="Enviar correos pendientes", replace_existing=True,
    )
    programador.add_job(
        tareas.limpiar_intentos, "cron", hour=3, minute=15,
        id="limpiar_intentos", name="Borrar intentos, sesiones y enlaces antiguos", replace_existing=True,
    )
    hora, minuto = hora_ingesta()
    programador.add_job(
        tareas.ingesta_diaria, "cron", hour=hora, minute=minuto,
        id="ingesta_diaria", name="Ingesta diaria de WeatherLink y Phytech", replace_existing=True,
    )
    programador.add_job(
        _vigilar, "interval", seconds=INTERVALO_VIGILANCIA_S,
        id="vigilar_ingestas", name="Cerrar y repetir ingestas interrumpidas", replace_existing=True,
    )
    arranque = ingesta_al_arrancar(ahora or dt.datetime.now(zona_lima()))
    if arranque is not None:
        programador.add_job(
            tareas.ingesta_diaria, "date", run_date=arranque,
            id="ingesta_al_arrancar", name="Ingesta del día al arrancar", replace_existing=True,
        )
    return programador


def crear_programador(*, en_segundo_plano: bool) -> BaseScheduler:
    clase = BackgroundScheduler if en_segundo_plano else BlockingScheduler
    return configurar(clase(timezone=zona_lima(), job_defaults=JOB_DEFAULTS))
