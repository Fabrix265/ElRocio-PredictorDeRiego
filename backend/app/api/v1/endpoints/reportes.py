"""Dashboard y exportación para refinamiento (F5).

| Ruta | Quién |
|---|---|
| ``GET /dashboard?modulo_id`` | todos (P: sin «aplicado vs modelo») |
| ``GET /exportaciones/refinamiento.csv?desde&hasta`` | A |
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import MAX_ID_BD, Contexto, DbSesion, UsuarioHabilitado, requiere_rol
from app.models import Usuario
from app.models.enums import RolUsuario
from app.schemas.reportes import DashboardSalida
from app.services import reportes_service

router = APIRouter()

Admin = Annotated[Usuario, Depends(requiere_rol(RolUsuario.admin))]


@router.get("/dashboard", response_model=DashboardSalida)
def dashboard(
    usuario: UsuarioHabilitado, db: DbSesion, modulo_id: Annotated[int, Query(ge=1, le=MAX_ID_BD)],
) -> dict:
    """KPIs de ayer y pronóstico de 5 días (frescura y «Hoy y mañana» tienen sus endpoints)."""
    return reportes_service.dashboard(db, modulo_id, usuario)


@router.get("/exportaciones/refinamiento.csv")
def refinamiento(
    usuario: Admin, db: DbSesion, contexto: Contexto,
    desde: dt.date | None = None, hasta: dt.date | None = None,
) -> Response:
    """CSV para refinar el modelo (§2.4): una fila por cronograma × turno × ciclo."""
    contenido, nombre = reportes_service.refinamiento_csv(db, desde, hasta, usuario, contexto)
    return Response(contenido, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nombre}"'})
