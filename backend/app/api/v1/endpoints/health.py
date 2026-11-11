"""Estado del servicio (público). ``modelo``: versión cargada (null hasta la primera generación)."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.seguridad import problemas_rol_conexion
from app.db.session import bd_disponible, get_db
from app.ml.model_loader import estado_modelo

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    bd_ok = bd_disponible(db)
    rol_bd = None
    if bd_ok:
        try:
            rol_bd = "inseguro" if problemas_rol_conexion(db) else "ok"
        except Exception:  # noqa: BLE001 - el health solo informa el estado
            db.rollback()
            rol_bd = "error"
        if rol_bd != "ok":
            logger.warning("Health: el rol de la base de datos no es riego_app o tiene privilegios de más")
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if bd_ok and rol_bd == "ok" else "degradado",
        "app": settings.app_name,
        "entorno": settings.app_env,
        "bd": "ok" if bd_ok else "error",
        # "inseguro": DATABASE_URL usa el dueño, un superusuario o un rol con BYPASSRLS.
        "rol_bd": rol_bd,
        "modelo": estado_modelo(),
    }
