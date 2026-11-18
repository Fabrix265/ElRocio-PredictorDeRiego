"""Configuración de la conexión a Fabric (variables ``FABRIC_*``).

Se leen de las variables del proceso y, si existe, de ``backend/.env.fabric`` (fuera de git; ver
``backend/.env.fabric.example``). Es un archivo aparte de ``backend/.env`` para poder usarlo en
local aunque ``RIEGO_SIN_ENV_FILE=1`` desactive el ``.env`` principal.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import BACKEND_ROOT

ARCHIVO_ENV_FABRIC = BACKEND_ROOT / ".env.fabric"
_IDENTIFICADOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")


class ConfiguracionFabric(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FABRIC_",
        env_file=ARCHIVO_ENV_FABRIC,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    servidor: str = ""
    base_datos: str = "LH_SILVER_GR"
    esquema: str = "dbo"
    tabla: str = "silver_galileo_consolas"
    # Consola Galileo del fundo (columna ``consola``); vacío = todas.
    consola: str = "GALENSUENO1"
    # usuario: cuenta de Entra ID con usuario y contraseña (falla si la cuenta exige MFA).
    # servicio: service principal (FABRIC_USUARIO = client id, FABRIC_CLAVE = secreto).
    autenticacion: Literal["usuario", "servicio"] = "usuario"
    usuario: str = ""
    clave: SecretStr = SecretStr("")
    # Inquilino de Entra ID para el modo "servicio" (p. ej. gruporocio.com o su GUID).
    inquilino: str = ""
    timeout_s: int = 30

    @property
    def inquilino_efectivo(self) -> str:
        if self.inquilino:
            return self.inquilino
        if "@" in self.usuario:
            return self.usuario.rsplit("@", 1)[1]
        return "organizations"

    @property
    def configurada(self) -> bool:
        return bool(self.servidor and self.usuario and self.clave.get_secret_value())

    def faltantes(self) -> list[str]:
        return [nombre for nombre, valor in (
            ("FABRIC_SERVIDOR", self.servidor),
            ("FABRIC_USUARIO", self.usuario),
            ("FABRIC_CLAVE", self.clave.get_secret_value()),
        ) if not valor]

    def tabla_calificada(self) -> str:
        """``[esquema].[tabla]`` validados (no admiten nada que no sea un identificador simple)."""
        for valor in (self.esquema, self.tabla):
            if not _IDENTIFICADOR.match(valor):
                raise ValueError(f"Identificador no válido en FABRIC_ESQUEMA/FABRIC_TABLA: {valor!r}")
        return f"[{self.esquema}].[{self.tabla}]"
