"""Configuración del backend (variables de entorno y ``backend/.env``).

Las variables de entorno del proceso tienen prioridad sobre ``backend/.env``. La lista
completa, con comentarios, está en ``backend/.env.example``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


def _lista(valor: str) -> list[str]:
    return [parte.strip() for parte in valor.split(",") if parte.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Aplicación
    app_name: str = "Sistema de Plan de Riego - Grupo El Rocío"
    app_env: Literal["development", "test", "production"] = "development"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"
    timezone: str = "America/Lima"

    # Base de datos
    database_url: str = ""
    database_url_migraciones: str = ""
    # auto: NullPool si la URL usa el puerto 6543 (pooler de Supabase en modo transacción);
    # null: siempre NullPool; queue: pool normal de SQLAlchemy.
    db_pool: Literal["auto", "null", "queue"] = "auto"
    riego_app_password: SecretStr | None = None

    # Tokens y cookies
    jwt_secret: SecretStr = SecretStr("")
    jwt_issuer: str = "riego-el-rocio"
    jwt_audience: str = "riego-el-rocio-web"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    password_reset_minutes: int = 30
    cookie_secure: bool = True
    cookie_samesite: Literal["strict", "lax", "none"] = "strict"

    # Web
    frontend_url: str = "http://localhost:5173"
    cors_origins: str = ""
    trusted_proxies: str = "127.0.0.1"

    # Correo (SMTP vacío = modo archivo en backend/var/correos)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: SecretStr = SecretStr("")
    smtp_from: str = ""
    smtp_starttls: bool = True

    # Phytech
    phytech_api_key: SecretStr = SecretStr("")
    phytech_api_secret: SecretStr = SecretStr("")
    phytech_api_base_url: str = "https://us-api.phytech.com"
    phytech_area_id: int = 12537
    phytech_plot_id: int = 70208
    phytech_project_id: int = 907557

    # WeatherLink
    weatherlink_api_key: SecretStr = SecretStr("")
    weatherlink_api_secret: SecretStr = SecretStr("")
    weatherlink_api_base_url: str = "https://api.weatherlink.com/v2"
    weatherlink_station_id: int = 28494

    # Modelo
    ml_model_path: str = "ml/models/plan_riego/actual/modelo_plan_riego.joblib"
    ml_model_sha256: str = ""

    # Tareas y cargas
    ingesta_hora: str = "05:00"
    scheduler_enabled: bool = False
    upload_max_mb: int = 15

    @field_validator("ingesta_hora")
    @classmethod
    def _validar_hora(cls, valor: str) -> str:
        partes = valor.split(":")
        if len(partes) != 2 or not all(p.isdigit() for p in partes):
            raise ValueError("INGESTA_HORA debe tener el formato HH:MM")
        hora, minuto = int(partes[0]), int(partes[1])
        if not (0 <= hora < 24 and 0 <= minuto < 60):
            raise ValueError("INGESTA_HORA fuera de rango")
        return f"{hora:02d}:{minuto:02d}"

    @model_validator(mode="after")
    def _validar_produccion(self) -> Settings:
        if self.app_env != "production":
            return self
        problemas = []
        if self.debug:
            problemas.append("DEBUG debe ser false")
        if len(self.jwt_secret.get_secret_value()) < 32:
            problemas.append("JWT_SECRET debe tener al menos 32 caracteres")
        if not self.cookie_secure:
            problemas.append("COOKIE_SECURE debe ser true")
        if not self.database_url:
            problemas.append("falta DATABASE_URL")
        if not self.frontend_url.startswith("https://"):
            problemas.append("FRONTEND_URL debe usar https")
        if problemas:
            raise ValueError("Configuración inválida para producción: " + "; ".join(problemas))
        return self

    @property
    def es_produccion(self) -> bool:
        return self.app_env == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        """Orígenes permitidos; si CORS_ORIGINS está vacío se usa FRONTEND_URL."""
        origenes = _lista(self.cors_origins)
        return origenes or [self.frontend_url.rstrip("/")]

    @property
    def trusted_proxy_list(self) -> list[str]:
        return _lista(self.trusted_proxies)

    @property
    def url_migraciones(self) -> str:
        """URL para Alembic (rol dueño, puerto 5432); si falta, DATABASE_URL."""
        return self.database_url_migraciones or self.database_url

    @property
    def ml_model_path_abs(self) -> Path:
        ruta = Path(self.ml_model_path)
        return ruta if ruta.is_absolute() else REPO_ROOT / ruta


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
