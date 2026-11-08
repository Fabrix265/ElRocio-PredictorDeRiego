from fastapi import APIRouter

from app.api.v1.endpoints import auditoria, auth, catalogo, health, usuarios
from app.api.v1.endpoints import riego as riego_endpoints
from app.api.v1.endpoints import datos, ingestas

api_router = APIRouter()
api_router.include_router(health.router, tags=["salud"])
api_router.include_router(auth.router, tags=["autenticación"])
api_router.include_router(usuarios.router, tags=["usuarios"])
api_router.include_router(auditoria.router, tags=["auditoría"])
api_router.include_router(catalogo.router, tags=["catálogos"])
api_router.include_router(riego_endpoints.router, tags=["riego aplicado"])
api_router.include_router(datos.router, tags=["datos de campo"])
api_router.include_router(ingestas.router, tags=["ingestas"])
