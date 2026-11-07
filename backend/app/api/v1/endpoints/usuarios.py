"""Gestión de usuarios (solo admin)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import Contexto, DbSesion, requiere_rol
from app.models import Usuario
from app.models.enums import RolUsuario
from app.repositories import usuarios as repo_usuarios
from app.schemas.usuarios import PasswordTemporalEntrada, UsuarioCrear, UsuarioEditar, UsuarioSalida
from app.services import usuario_service
from app.services.usuario_service import DatosUsuarioNuevo

router = APIRouter(prefix="/usuarios")

Admin = Annotated[Usuario, Depends(requiere_rol(RolUsuario.admin))]


@router.get("", response_model=list[UsuarioSalida])
def listar(
    _admin: Admin,
    db: DbSesion,
    q: Annotated[str | None, Query(max_length=100)] = None,
    rol: RolUsuario | None = None,
    activo: bool | None = None,
) -> list[Usuario]:
    return repo_usuarios.listar(db, q=q, rol=rol, activo=activo)


@router.post("", response_model=UsuarioSalida, status_code=status.HTTP_201_CREATED)
def crear(datos: UsuarioCrear, admin: Admin, db: DbSesion, contexto: Contexto) -> Usuario:
    return usuario_service.crear(
        db,
        DatosUsuarioNuevo(
            username=datos.username,
            nombre=datos.nombre,
            correo=datos.correo,
            rol=datos.rol,
            password=datos.password_temporal,
        ),
        actor=admin,
        contexto=contexto,
        debe_cambiar_password=True,
    )


@router.get("/{usuario_id}", response_model=UsuarioSalida)
def obtener(usuario_id: int, _admin: Admin, db: DbSesion) -> Usuario:
    return usuario_service.obtener(db, usuario_id)


@router.patch("/{usuario_id}", response_model=UsuarioSalida)
def editar(
    usuario_id: int, datos: UsuarioEditar, admin: Admin, db: DbSesion, contexto: Contexto
) -> Usuario:
    cambios = datos.model_dump(exclude_unset=True, exclude_none=True)
    return usuario_service.editar(db, usuario_id, cambios, actor=admin, contexto=contexto)


@router.post("/{usuario_id}/password-temporal", response_model=UsuarioSalida)
def password_temporal(
    usuario_id: int, datos: PasswordTemporalEntrada, admin: Admin, db: DbSesion, contexto: Contexto
) -> Usuario:
    return usuario_service.asignar_password_temporal(
        db, usuario_id, datos.password_temporal, actor=admin, contexto=contexto
    )
