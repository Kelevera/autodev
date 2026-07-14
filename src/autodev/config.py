"""Application settings loaded from `AUTODEV_*` environment variables and .env."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for autodev."""

    model_config = SettingsConfigDict(
        env_prefix="AUTODEV_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_provider: str = "ollama"
    api_key: str = ""
    model: str = ""  # empty -> provider default (see llm.client.DEFAULT_MODELS)
    base_url: str = ""  # empty -> provider default endpoint
    max_tokens: int = 4096
    db_path: str = "autodev.db"
    repo_path: str = "."
    src_dir: str = "src"
    tests_dir: str = "tests"
    max_jobs_per_run: int = 3


def get_settings() -> Settings:
    """Return settings freshly resolved from the environment and .env file."""
    return Settings()
