"""Esquemas de usuarios (contrato HTTP de ``/api/v1/usuarios``)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.models.enums import RolUsuario

_PATRON_USERNAME = re.compile(r"^[a-z0-9._-]{3,60}$")


def _validar_username(valor: str) -> str:
    valor = valor.strip().lower()
    if not _PATRON_USERNAME.fullmatch(valor):
        raise ValueError(
            "El usuario debe tener de 3 a 60 caracteres: letras sin tilde, números, punto, "
            "guion o guion bajo."
        )
    return valor


Username = Annotated[str, AfterValidator(_validar_username)]
Nombre = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
Correo = Annotated[EmailStr, AfterValidator(lambda v: v.strip().lower()), Field(max_length=254)]
PasswordEntrada = Annotated[str, Field(min_length=1, max_length=256)]


class UsuarioSalida(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    nombre: str
    correo: str
    rol: RolUsuario
    activo: bool
    debe_cambiar_password: bool
    ultimo_acceso_at: datetime | None


class UsuarioCrear(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: Username
    nombre: Nombre
    correo: Correo
    rol: RolUsuario
    password_temporal: PasswordEntrada


class UsuarioEditar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nombre: Nombre | None = None
    correo: Correo | None = None
    rol: RolUsuario | None = None
    activo: bool | None = None


class PasswordTemporalEntrada(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password_temporal: PasswordEntrada
