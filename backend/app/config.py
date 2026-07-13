"""Application settings.

Single source of truth for environment configuration, read once at process
start via `pydantic-settings`. Adapters (boto3 clients, the SQLAlchemy async
engine, etc.) receive values from here rather than reading `os.environ`
directly — see design.md §22.4/§22.6 for the local-vs-production rationale
(only `.env.local` changes; adapter code never branches on environment).
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env.local",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "local"

    database_url: str = (
        "postgresql+asyncpg://app_user:dev_only_password@localhost:5432/kureha_dev"
    )

    # boto3 clients read this and fall back to real AWS when it's empty
    # (design.md §22.6): None/"" -> AWS real, "http://localhost:4566" -> LocalStack.
    aws_endpoint_url: str | None = None
    aws_default_region: str = "us-east-1"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
