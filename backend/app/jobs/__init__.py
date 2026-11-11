"""Tareas programadas (APScheduler): cola de correos y mantenimiento.

Proceso aparte en producción (``python -m app.jobs``) o dentro de la API en desarrollo
(``SCHEDULER_ENABLED=true``). La ingesta de las 05:00 se agrega en la fase 2.
"""
