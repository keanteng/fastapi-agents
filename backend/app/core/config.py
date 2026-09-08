from __future__ import annotations

import logging
import re

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Default to a placeholder so the app imports without creds; real
    # DeepSeek calls require a valid key set in the environment.
    deepseek_api_key: str = Field(default="stub", alias="DEEPSEEK_API_KEY")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL"
    )

    app_host: str = Field(default="0.0.0.0", alias="APP_HOST")
    app_port: int = Field(default=8000, alias="APP_PORT")

    # Allowed CORS origins, e.g. ["http://localhost:5173"]. "*" allows any.
    cors_origins: list[str] = Field(default_factory=lambda: ["*"], alias="CORS_ORIGINS")

    # Runs: wall-clock budget for a single run (seconds).
    run_timeout_seconds: int = Field(default=300, alias="RUN_TIMEOUT_SECONDS")

    @field_validator("deepseek_api_key", mode="before")
    @classmethod
    def _clean_api_key(cls, value: str) -> str:
        key = re.sub(r"^your-", "", value.strip()).strip("'\"")
        if key != value:
            logger.warning("DEEPSEEK_API_KEY normalized (stripped quotes/prefix)")
        return key

    # Database. Default to a local Postgres; tests swap to an in-memory
    # SQLite URL via the session fixtures (see tests/conftest.py).
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/agents",
        alias="DATABASE_URL",
    )
    db_pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    db_echo: bool = Field(default=False, alias="DB_ECHO")

    # Document uploads + compliance.
    upload_dir: str = Field(default="./data/uploads", alias="UPLOAD_DIR")
    upload_max_bytes: int = Field(default=20 * 1024 * 1024, alias="UPLOAD_MAX_BYTES")
    # Vision model that augments textract-style extraction with visual analysis.
    doc_vision_model: str = Field(
        default="deepseek-v4-flash-vision-exp", alias="DOC_VISION_MODEL"
    )
    doc_vision_enabled: bool = Field(default=True, alias="DOC_VISION_ENABLED")
    doc_max_vision_pages: int = Field(default=8, alias="DOC_MAX_VISION_PAGES")
    # Optional YAML file of extra sensitive-data rules (see app/documents/rules.py).
    compliance_rules_path: str | None = Field(default=None, alias="COMPLIANCE_RULES_PATH")
    # Upper bound on document characters fed to the compliance judge.
    compliance_max_text_chars: int = Field(
        default=60_000, alias="COMPLIANCE_MAX_TEXT_CHARS"
    )


settings = Settings()
