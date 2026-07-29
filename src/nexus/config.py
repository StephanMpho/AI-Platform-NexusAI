"""Typed settings. The only place in the codebase that reads the environment.

Nested sections use a double underscore, so NEXUS_DATABASE__URL populates
Settings.database.url. Adding a provider is configuration, not code.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class DatabaseSettings(BaseModel):
    url: str = "postgresql+asyncpg://nexus:nexus@localhost:5432/nexus"
    pool_size: int = 10
    echo: bool = False


class RedisSettings(BaseModel):
    url: str = "redis://localhost:6379/0"


class StorageSettings(BaseModel):
    endpoint: str = "http://localhost:9000"
    access_key: SecretStr = SecretStr("minioadmin")
    secret_key: SecretStr = SecretStr("minioadmin")
    bucket: str = "nexus-documents"


class TelemetrySettings(BaseModel):
    enabled: bool = True
    otlp_endpoint: str = "http://localhost:4317"
    service_name: str = "nexus-api"
    sample_rate: float = 1.0


class ProviderSettings(BaseModel):
    """Credentials only. Model catalogue lives in the database, not here."""

    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_endpoint: str | None = None

    def configured(self) -> list[str]:
        """Which providers have credentials. `mock` is always available."""
        available = ["mock"]
        if self.openai_api_key:
            available.append("openai")
        if self.anthropic_api_key:
            available.append("anthropic")
        if self.azure_openai_api_key and self.azure_openai_endpoint:
            available.append("azure_openai")
        return available


class AuthSettings(BaseModel):
    issuer: str = "http://localhost:8080/realms/nexus"
    client_id: str = "nexus-console"
    client_secret: SecretStr | None = None
    session_hours: int = 8
    # Local convenience only. Guarded at startup so it cannot reach production.
    dev_bypass: bool = False


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    env: Literal["local", "staging", "production"] = "local"
    log_level: str = "INFO"
    secret_key: SecretStr = SecretStr("change-me")

    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)
    providers: ProviderSettings = Field(default_factory=ProviderSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

    def validate_for_env(self) -> None:
        """Fail fast at startup rather than surprising us in production."""
        if self.env == "production":
            if self.auth.dev_bypass:
                raise RuntimeError("NEXUS_AUTH__DEV_BYPASS must be false in production")
            if self.secret_key.get_secret_value() == "change-me":
                raise RuntimeError("NEXUS_SECRET_KEY must be set in production")


@lru_cache
def get_settings() -> Settings:
    return Settings()
