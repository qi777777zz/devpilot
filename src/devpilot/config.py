from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
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
    worker_lease_seconds: int = Field(default=180, ge=5, le=3600)
    worker_max_attempts: int = Field(default=3, ge=1, le=20)
    context_token_budget: int = Field(default=3000, ge=256, le=100_000)
    workspace_storage_root: Path = Path("var/workspaces")
    patch_max_bytes: int = Field(default=200_000, ge=1024, le=5_000_000)
    patch_max_files: int = Field(default=20, ge=1, le=500)
    model_provider: Literal["deterministic", "openai"] = "deterministic"
    openai_api_key: SecretStr | None = None
    openai_model: str = Field(default="gpt-5.6", min_length=1, max_length=120)
    openai_base_url: str = "https://api.openai.com/v1"
    model_request_timeout_seconds: int = Field(default=120, ge=1, le=1800)

    @field_validator("allowed_repository_root")
    @classmethod
    def resolve_repository_root(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("workspace_storage_root")
    @classmethod
    def resolve_workspace_root(cls, value: Path) -> Path:
        return value.expanduser().resolve()

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_empty_api_key(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_model_lease_window(self) -> Settings:
        if (
            self.model_provider == "openai"
            and self.worker_lease_seconds <= self.model_request_timeout_seconds
        ):
            raise ValueError(
                "worker_lease_seconds must exceed model_request_timeout_seconds "
                "when the OpenAI provider is enabled"
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
