"""Motor y sesiones de base de datos.

Compatible con el pooler de Supabase en modo transacción (puerto 6543): sin *prepared
statements* (``prepare_threshold=None``) y sin pool propio (``NullPool``). El esquema se
indica en cada tabla, así que no se depende de ``search_path``.

Convención de transacciones (desde F2): los servicios hacen ``flush`` y **quien llama** hace
``commit``: la dependencia ``DbSesion`` de los endpoints (``app.api.deps.unidad_de_trabajo``), la
CLI y las tareas programadas con :func:`unidad_de_trabajo`. Las excepciones (lo que debe persistir
antes de lanzar un error: intentos del límite, auditoría de un login fallido, reclamo de la cola de
correos) están documentadas en cada servicio.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings

PUERTO_POOLER_TRANSACCION = 6543


def normalizar_url(url: str | URL) -> URL:
    """Usa siempre el driver psycopg 3 (``postgresql+psycopg``)."""
    if not url:
        raise RuntimeError("Falta DATABASE_URL en la configuración (ver backend/.env.example)")
    url = make_url(url)
    if url.drivername in ("postgresql", "postgres", "postgresql+psycopg2"):
        url = url.set(drivername="postgresql+psycopg")
    return url


def usa_null_pool(url: URL, modo: str | None = None) -> bool:
    modo = modo or settings.db_pool
    if modo == "null":
        return True
    if modo == "queue":
        return False
    return url.port == PUERTO_POOLER_TRANSACCION


def opciones_engine(url: URL, modo_pool: str | None = None) -> tuple[dict, dict]:
    """``(connect_args, opciones de create_engine)`` según la URL y DB_POOL."""
    connect_args: dict = {"application_name": "riego-backend", "connect_timeout": 10}
    opciones: dict = {"pool_pre_ping": True}
    if usa_null_pool(url, modo_pool):
        opciones["poolclass"] = NullPool
        connect_args["prepare_threshold"] = None  # sin prepared statements (pooler 6543)
    else:
        opciones.update(pool_size=5, max_overflow=5, pool_recycle=1800)
    return connect_args, opciones


def crear_engine(url: str | URL | None = None, *, modo_pool: str | None = None, **kwargs) -> Engine:
    url = normalizar_url(url or settings.database_url)
    connect_args, opciones = opciones_engine(url, modo_pool)
    connect_args.update(kwargs.pop("connect_args", {}))
    opciones.update(kwargs)
    return create_engine(url, connect_args=connect_args, **opciones)


@lru_cache
def get_engine() -> Engine:
    """Motor de la aplicación (se crea al primer uso, no al importar)."""
    return crear_engine()


SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def nueva_sesion() -> Session:
    return SessionLocal(bind=get_engine())


@contextmanager
def unidad_de_trabajo(db: Session | None = None) -> Iterator[Session]:
    """Transacción de la CLI y las tareas: commit al salir sin error, rollback si hay excepción.

    Sin ``db`` abre una sesión nueva y la cierra al terminar.
    """
    propia = db is None
    sesion = nueva_sesion() if propia else db
    try:
        yield sesion
        sesion.commit()
    except BaseException:
        sesion.rollback()
        raise
    finally:
        if propia:
            sesion.close()


def get_db() -> Iterator[Session]:
    """Dependencia de FastAPI: una sesión por petición (sin commit; ver ``DbSesion``)."""
    db = nueva_sesion()
    try:
        yield db
    finally:
        db.close()


def bd_disponible(db: Session) -> bool:
    try:
        db.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - el health solo informa el estado
        db.rollback()
        return False
