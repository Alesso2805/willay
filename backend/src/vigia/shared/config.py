"""Configuración por variables de entorno (prefijo `VIGIA_`). Nunca secretos en el repo."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIGIA_", extra="ignore")

    # URL de la API y los workers (rol vigia_app), p. ej. postgresql+asyncpg://...
    database_url: str
    log_level: str = "INFO"
    # Cada worker toca aquí su archivo de latido; el healthcheck de Compose revisa su antigüedad.
    heartbeat_dir: Path = Path("/tmp/vigia")

    # OIDC (Keycloak). El issuer es la URL pública con la que el navegador pidió el token
    # (localhost); el JWKS se descarga por la red interna (keycloak:8080). Son distintos.
    oidc_issuer: str = "http://localhost:8080/realms/vigia"
    oidc_jwks_url: str = "http://keycloak:8080/realms/vigia/protocol/openid-connect/certs"
    oidc_audience: str = "vigia-api"

    # Orígenes del panel que pueden llamar a la API desde el navegador (JSON en el entorno).
    cors_origins: list[str] = ["http://localhost:4200"]

    # URL pública de la API: base de los enlaces que salen en las alertas (confirmación).
    public_url: str = "http://localhost:8000"

    # Correo saliente (dispatcher). En local, Mailpit: sin TLS ni credenciales.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "Vigía <alertas@vigia.local>"
    smtp_start_tls: bool = False
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_timeout_s: float = 10.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
