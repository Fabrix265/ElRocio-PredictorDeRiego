"""Aplicación FastAPI del Sistema de Plan de Riego (Grupo El Rocío).

En producción se arranca con ``python -m app`` (``app/__main__.py``): un worker y la IP real
tomada de ``X-Forwarded-For`` solo desde TRUSTED_PROXIES.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.manejadores import registrar_manejadores
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.logging import configurar_logging
from app.core.middleware import CabecerasSeguridad

logger = logging.getLogger("app")


def verificar_rol_bd(config: Settings) -> list[str]:
    """Comprueba al arrancar que DATABASE_URL usa ``riego_app`` (§7: sin privilegios de dueño).

    En producción un rol inseguro aborta el arranque; en los demás entornos solo se avisa en el
    log (``/health`` además queda degradado). Si la BD no responde, se registra y se sigue.
    """
    from app.db.seguridad import problemas_rol_conexion
    from app.db.session import crear_engine

    try:
        motor = crear_engine(config.database_url, modo_pool="null")
        try:
            with motor.connect() as conexion:
                problemas = problemas_rol_conexion(conexion)
        finally:
            motor.dispose()
    except Exception as error:  # noqa: BLE001 - sin BD el health lo informa
        logger.error("No se pudo comprobar el rol de la base de datos al arrancar (%s)",
                     type(error).__name__)
        return []
    if problemas:
        mensaje = "La aplicación no se conecta con un rol seguro: " + "; ".join(problemas)
        if config.es_produccion:
            raise RuntimeError(mensaje + ". DATABASE_URL debe usar el rol riego_app.")
        logger.warning("%s (en producción no arrancaría)", mensaje)
    return problemas


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        # Después de que uvicorn configuró sus handlers: el filtro de redacción los cubre a todos.
        configurar_logging(logging.DEBUG if config.debug else logging.INFO)
        if config.app_env != "test":
            verificar_rol_bd(config)
        programador = None
        if config.scheduler_enabled:
            from app.jobs.runner import crear_programador

            programador = crear_programador(en_segundo_plano=True)
            programador.start()
            logger.info("Tareas programadas corriendo dentro de la API (SCHEDULER_ENABLED=true)")
        try:
            yield
        finally:
            if programador is not None:
                programador.shutdown(wait=False)
            # Libera las conexiones del pool al apagar.
            from app.db.session import get_engine

            if get_engine.cache_info().currsize:
                get_engine().dispose()

    docs = not config.es_produccion
    app = FastAPI(
        title=config.app_name,
        # Nunca: con debug=True Starlette devuelve el traceback (SQL y parámetros) al cliente.
        # Los errores no controlados van al log (redactado) y al manejador genérico.
        debug=False,
        lifespan=lifespan,
        docs_url="/docs" if docs else None,
        redoc_url=None,
        openapi_url=f"{config.api_v1_prefix}/openapi.json" if docs else None,
    )

    registrar_manejadores(app)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
        max_age=600,
    )
    # El último agregado es el más externo: las cabeceras también van en errores y preflights.
    app.add_middleware(CabecerasSeguridad, hsts=config.es_produccion)

    app.include_router(api_router, prefix=config.api_v1_prefix)
    return app


app = create_app()
