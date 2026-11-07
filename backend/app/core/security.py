"""Contraseñas (argon2id), tokens JWT de acceso (HS256) y tokens opacos.

- Contraseñas: argon2id con los parámetros por defecto de argon2-cffi (RFC 9106, perfil de
  baja memoria). Se normalizan a Unicode NFC antes de hashear y verificar.
- Access token: JWT HS256 con ``sub``, ``ver`` (token_version), ``iat``, ``exp``, ``typ``,
  ``iss`` y ``aud``. El algoritmo está fijado al decodificar (``alg: none`` y otros se rechazan).
- Refresh y recuperación: tokens opacos aleatorios; en la BD solo se guarda su SHA-256.
"""

from __future__ import annotations

import hashlib
import secrets
import unicodedata
from datetime import timedelta
from functools import lru_cache
from typing import Any

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings
from app.core.tiempo import ahora_utc

ALGORITMO_JWT = "HS256"
TIPO_ACCESS = "access"

LARGO_MINIMO_PASSWORD = 10
LARGO_MAXIMO_PASSWORD = 128

_hasher = PasswordHasher(type=Type.ID)


def _normalizar(password: str) -> str:
    return unicodedata.normalize("NFC", password)


# --- Contraseñas --------------------------------------------------------------

def hash_password(password: str) -> str:
    return _hasher.hash(_normalizar(password))


def verificar_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, _normalizar(password))
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def necesita_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


@lru_cache
def _hash_ficticio() -> str:
    return _hasher.hash(secrets.token_urlsafe(24))


def verificar_password_ficticia(password: str) -> None:
    """Gasta el mismo tiempo que una verificación real (usuario inexistente o inactivo)."""
    verificar_password(password, _hash_ficticio())


def errores_politica_password(password: str, username: str | None = None) -> list[str]:
    """Política de §7: mínimo 10 caracteres, letras y números, distinta del usuario."""
    errores: list[str] = []
    if len(password) < LARGO_MINIMO_PASSWORD:
        errores.append(f"La contraseña debe tener al menos {LARGO_MINIMO_PASSWORD} caracteres.")
    if len(password) > LARGO_MAXIMO_PASSWORD:
        errores.append(f"La contraseña no puede tener más de {LARGO_MAXIMO_PASSWORD} caracteres.")
    if not (any(c.isalpha() for c in password) and any(c.isdecimal() for c in password)):
        errores.append("La contraseña debe incluir letras y números.")
    if username and password.strip().casefold() == username.strip().casefold():
        errores.append("La contraseña no puede ser igual al nombre de usuario.")
    return errores


# --- JWT de acceso ------------------------------------------------------------

def _secreto() -> str:
    secreto = settings.jwt_secret.get_secret_value()
    if not secreto:
        raise RuntimeError("Falta JWT_SECRET en la configuración (ver backend/.env.example)")
    return secreto


def crear_access_token(usuario_id: int, token_version: int) -> tuple[str, int]:
    """Devuelve ``(token, segundos_de_vigencia)``."""
    vigencia = settings.access_token_minutes * 60
    ahora = ahora_utc()
    claims = {
        "sub": str(usuario_id),
        "ver": token_version,
        "typ": TIPO_ACCESS,
        "iat": int(ahora.timestamp()),
        "exp": int((ahora + timedelta(seconds=vigencia)).timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(claims, _secreto(), algorithm=ALGORITMO_JWT), vigencia


def decodificar_access_token(token: str) -> dict[str, Any]:
    """Valida firma, algoritmo, vigencia, emisor, audiencia y tipo. Lanza ``jwt.InvalidTokenError``."""
    claims = jwt.decode(
        token,
        _secreto(),
        algorithms=[ALGORITMO_JWT],
        audience=settings.jwt_audience,
        issuer=settings.jwt_issuer,
        options={"require": ["sub", "ver", "typ", "iat", "exp", "iss", "aud"]},
    )
    if claims.get("typ") != TIPO_ACCESS:
        raise jwt.InvalidTokenError("tipo de token incorrecto")
    if not isinstance(claims.get("ver"), int) or not str(claims["sub"]).isdigit():
        raise jwt.InvalidTokenError("claims inválidos")
    return claims


# --- Tokens opacos ------------------------------------------------------------

def generar_token_opaco() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
