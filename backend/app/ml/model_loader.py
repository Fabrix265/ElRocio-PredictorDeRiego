"""Carga del modelo ``.joblib`` de riego_ml con verificación de sha256 (H10, D2).

- ``joblib.load`` ejecuta código (pickle): antes de cargar se calcula el sha256 del archivo y se
  compara con ``ML_MODEL_SHA256``. En producción es obligatorio; en desarrollo, si falta, se avisa
  en el log y se carga igual.
- El modelo se carga una vez por proceso (perezoso) y se protege con ``CANDADO_MODELO``: el bucle de
  generación lo toma antes de los candados de la BD (§3.1).
- ``registrar_version`` deja el modelo en ``modelo_version`` (``ON CONFLICT DO NOTHING``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errores import ErrorApp
from app.models import ModeloVersion

logger = logging.getLogger(__name__)

CANDADO_MODELO = threading.Lock()
_carga = threading.Lock()


class ModeloNoDisponible(ErrorApp):
    status_code = 503
    detail = "El modelo de predicción no está disponible"


@dataclass(frozen=True)
class ModeloCargado:
    plan: Any  # riego_ml.modeling.planificador.PlanRiego
    version: str
    sha256: str
    ruta: Path
    metadatos: dict[str, Any]


_cache: ModeloCargado | None = None


def sha256_archivo(ruta: Path) -> str:
    h = hashlib.sha256()
    with ruta.open("rb") as archivo:
        for bloque in iter(lambda: archivo.read(1 << 20), b""):
            h.update(bloque)
    return h.hexdigest()


def _metadatos(ruta: Path) -> dict[str, Any]:
    archivo = ruta.parent / "metadata.json"
    if not archivo.exists():
        return {}
    try:
        return json.loads(archivo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("No se pudo leer %s", archivo.name)
        return {}


def cargar_modelo() -> ModeloCargado:
    """Modelo del proceso; lo carga la primera vez. Lanza ``ModeloNoDisponible`` si no se puede."""
    global _cache
    if _cache is not None:
        return _cache
    with _carga:
        if _cache is not None:
            return _cache
        ruta = settings.ml_model_path_abs
        if not ruta.exists():
            raise ModeloNoDisponible("No se encontró el modelo de predicción (ML_MODEL_PATH).")
        huella = sha256_archivo(ruta)
        esperado = settings.ml_model_sha256.strip().lower()
        if esperado and huella != esperado:
            logger.error("El sha256 del modelo no coincide con ML_MODEL_SHA256: no se carga")
            raise ModeloNoDisponible("El archivo del modelo no coincide con su huella (ML_MODEL_SHA256).")
        if not esperado:
            if settings.es_produccion:
                raise ModeloNoDisponible("Falta ML_MODEL_SHA256: en producción el modelo debe verificarse.")
            logger.warning("ML_MODEL_SHA256 vacío: el modelo se carga sin verificar (sha256 %s)", huella)

        import joblib
        from riego_ml.modeling.planificador import PlanRiego

        plan = joblib.load(ruta)
        if not isinstance(plan, PlanRiego):
            raise ModeloNoDisponible("El archivo del modelo no contiene un PlanRiego.")
        metadatos = _metadatos(ruta)
        version = str(metadatos.get("version") or huella[:12])
        _cache = ModeloCargado(plan=plan, version=version, sha256=huella, ruta=ruta, metadatos=metadatos)
        logger.info("Modelo de predicción cargado: versión %s", version)
        return _cache


def registrar_version(db: Session, modelo: ModeloCargado) -> int:
    """Id de ``modelo_version`` (lo inserta si no existe)."""
    db.execute(
        insert(ModeloVersion)
        .values(version=modelo.version, sha256=modelo.sha256, metadatos=modelo.metadatos,
                ruta=modelo.ruta.name)
        .on_conflict_do_nothing(index_elements=["version"])
    )
    return db.execute(select(ModeloVersion.id).where(ModeloVersion.version == modelo.version)).scalar_one()


def estado_modelo() -> dict[str, Any] | None:
    """Para el health: versión del modelo si ya se cargó (no fuerza la carga)."""
    if _cache is None:
        return None
    return {"version": _cache.version, "verificado": bool(settings.ml_model_sha256.strip())}
