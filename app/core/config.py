from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Default to a placeholder so the app imports without creds; real
    # DeepSeek calls require a valid key set in the environment.
    deepseek_api_key: str = Field(default="stub", alias="DEEPSEEK_API_KEY")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")

    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    # Database. Default to a local Postgres; tests swap to an in-memory
    # SQLite URL via the session fixtures (see tests/conftest.py).
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/agents",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_echo: bool = Field(default=False, alias="DB_ECHO")


settings = Settings()
