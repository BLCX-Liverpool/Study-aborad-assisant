from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Study Abroad Assistant API"
    app_env: str = "development"
    api_prefix: str = "/api"
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/study_abroad_assistant"
    redis_url: str = "redis://localhost:6379/0"

    llm_provider: str = "openai_compatible"
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    router_llm_model: str | None = None
    router_embedding_model: str | None = None
    notice_llm_model: str | None = None
    assignment_llm_model: str | None = None
    email_llm_model: str | None = None
    social_llm_model: str | None = None
    memory_llm_model: str | None = None
    llm_base_url: str = "https://api.openai.com/v1"
    llm_api_key: str = ""

    ocr_engine: str = "auto"
    ocr_pdf_render_scale: float = 2.0
    ocr_max_pages: int = 20
    deepdoc_python: Path = Path("./.venv_deepdoc/bin/python")
    deepdoc_model_home: Path | None = None
    deepdoc_timeout_seconds: int = 180

    qq_smtp_host: str = "smtp.qq.com"
    qq_smtp_port: int = 465
    qq_smtp_username: str = ""
    qq_smtp_password: str = ""
    qq_smtp_from_email: str = ""
    qq_smtp_from_name: str = "Study Abroad Assistant"

    outlook_smtp_host: str = "smtp.office365.com"
    outlook_smtp_port: int = 587
    outlook_smtp_username: str = ""
    outlook_smtp_password: str = ""
    outlook_smtp_from_email: str = ""
    outlook_smtp_from_name: str = "Study Abroad Assistant"

    upload_storage_dir: Path = Path("./.data/uploads")


@lru_cache
def get_settings() -> Settings:
    return Settings()
