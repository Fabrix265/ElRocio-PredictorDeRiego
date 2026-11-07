"""Estado del servicio (público). ``modelo`` se completa en la fase 3."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import bd_disponible, get_db

router = APIRouter()


@router.get("/health")
def health(response: Response, db: Session = Depends(get_db)) -> dict:
    bd_ok = bd_disponible(db)
    if not bd_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if bd_ok else "degradado",
        "app": settings.app_name,
        "entorno": settings.app_env,
        "bd": "ok" if bd_ok else "error",
        "modelo": None,
    }
