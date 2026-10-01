"""Configuration from environment variables (prefix `VIGIA_`). Never secrets in the repo."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VIGIA_", extra="ignore")

    # URL for the API and workers (vigia_app role), e.g. postgresql+asyncpg://...
    database_url: str
    log_level: str = "INFO"
    # Each worker touches its heartbeat file here; the Compose healthcheck checks its age.
    heartbeat_dir: Path = Path("/tmp/vigia")

    # OIDC (Keycloak). The issuer is the public URL the browser got the token from (localhost);
    # the JWKS is fetched over the internal network (keycloak:8080). They differ on purpose.
    oidc_issuer: str = "http://localhost:8080/realms/vigia"
    oidc_jwks_url: str = "http://keycloak:8080/realms/vigia/protocol/openid-connect/certs"
    oidc_audience: str = "vigia-api"

    # Dashboard origins allowed to call the API from the browser (JSON in the environment).
    cors_origins: list[str] = ["http://localhost:4200"]

    # Public API URL: base for the links sent in alerts (confirmation).
    public_url: str = "http://localhost:8000"

    # Outgoing mail (dispatcher). Locally, Mailpit: no TLS or credentials.
    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_from: str = "Willay <alertas@willay.local>"
    smtp_start_tls: bool = False
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_timeout_s: float = 10.0

    # Telegram bot (VIG-21/22): created with @BotFather; its token lives only in .env.
    # SecretStr masks it if the settings get logged. Without a token the telegram worker
    # starts disabled and the API does not generate links.
    telegram_bot_token: SecretStr | None = None
    telegram_bot_username: str | None = None
    telegram_api_url: str = "https://api.telegram.org"

    @field_validator("telegram_bot_token", "telegram_bot_username", mode="before")
    @classmethod
    def _empty_means_unset(cls, value: object) -> object:
        # Compose passes "" when the variable is missing from .env: that means "no bot".
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
