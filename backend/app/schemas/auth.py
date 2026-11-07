"""Esquemas de autenticación (contrato HTTP de ``/api/v1/auth``)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.usuarios import UsuarioSalida

# Límite generoso para no cortar contraseñas válidas, pero evitar cuerpos enormes en argon2.
MAX_PASSWORD_ENTRADA = 256


class Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)


class LoginEntrada(Entrada):
    username: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_ENTRADA)


class RecuperarEntrada(Entrada):
    identificador: str = Field(min_length=1, max_length=254, description="Usuario o correo")


class RestablecerEntrada(Entrada):
    token: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_ENTRADA)


class CambiarPasswordEntrada(Entrada):
    password_actual: str = Field(min_length=1, max_length=MAX_PASSWORD_ENTRADA)
    password_nueva: str = Field(min_length=1, max_length=MAX_PASSWORD_ENTRADA)


class SesionSalida(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = Field(description="Segundos de vigencia del access token")
    usuario: UsuarioSalida


class Mensaje(BaseModel):
    detail: str
