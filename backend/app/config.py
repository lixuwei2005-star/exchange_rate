from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All env-driven config. Reads from process env (which docker-compose loads from .env)."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    env: Literal["dev", "prod"] = "dev"

    database_url: str = "sqlite+aiosqlite:////data/rate.db"

    cors_allow_origins: str = "http://localhost:3000"

    fernet_key: str = Field(..., description="Fernet key for encrypting settings.value")
    jwt_secret: str = Field(..., description="JWT signing secret")
    jwt_expire_days: int = 7

    admin_username: str = "admin"
    admin_password: str = ""

    # Public name used in logs / health.
    app_name: str = "rate.005917.xyz"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]

    @property
    def cookie_secure(self) -> bool:
        return self.env != "dev"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
