from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="DEVPILOT_",
        extra="ignore",
    )

    app_name: str = "DevPilot"
    environment: str = "development"
    database_url: str = "sqlite:///./var/devpilot.db"
    allowed_repository_root: Path = Field(default_factory=Path.cwd)
    enable_local_execution: bool = False
    test_timeout_seconds: int = Field(default=120, ge=1, le=1800)
    in_process_worker: bool = True
    worker_poll_seconds: float = Field(default=1.0, ge=0.1, le=60)
    worker_lease_seconds: int = Field(default=30, ge=5, le=3600)
    worker_max_attempts: int = Field(default=3, ge=1, le=20)

    @field_validator("allowed_repository_root")
    @classmethod
    def resolve_repository_root(cls, value: Path) -> Path:
        return value.expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()
