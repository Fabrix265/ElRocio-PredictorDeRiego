"""Aplicación FastAPI del Sistema de Plan de Riego (Grupo El Rocío)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.manejadores import registrar_manejadores
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings


def create_app(config: Settings | None = None) -> FastAPI:
    config = config or get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        # Libera las conexiones del pool al apagar.
        from app.db.session import get_engine

        if get_engine.cache_info().currsize:
            get_engine().dispose()

    docs = not config.es_produccion
    app = FastAPI(
        title=config.app_name,
        debug=config.debug and not config.es_produccion,
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

    app.include_router(api_router, prefix=config.api_v1_prefix)
    return app


app = create_app()
