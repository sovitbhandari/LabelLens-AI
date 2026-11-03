"""Application settings loaded from environment / .env."""

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_name: str = "LabelLens AI"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://localhost:3000"
    admin_token: str = "dev-admin-token-change-me"

    database_url: str = "postgresql+psycopg://labellens:labellens@localhost:5432/labellens"
    test_database_url: str = (
        "postgresql+psycopg://labellens:labellens@localhost:5432/labellens_test"
    )

    dailymed_base_url: str = "https://dailymed.nlm.nih.gov/dailymed/services/v2"
    dailymed_download_base_url: str = "https://dailymed.nlm.nih.gov/dailymed"
    dailymed_timeout_seconds: float = 60.0
    dailymed_max_retries: int = 5
    dailymed_rate_limit_rps: float = 2.0

    embedding_provider: Literal["sentence_transformers", "openai"] = "sentence_transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    chunk_size: int = 800
    chunk_overlap: int = 120

    retrieval_top_k: int = 5
    rrf_k: int = 60

    llm_provider: Literal["auto", "openai", "gemini"] = "auto"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 60.0
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.5-flash"
    gemini_timeout_seconds: float = 90.0
    generation_temperature: float = 0.0

    @property
    def active_llm_provider(self) -> Literal["openai", "gemini"] | None:
        """Resolve which generative LLM is configured."""
        if self.llm_provider == "openai":
            return "openai" if self.openai_api_key else None
        if self.llm_provider == "gemini":
            return "gemini" if self.gemini_api_key else None
        # auto: prefer Gemini when present, else OpenAI
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        return None

    # Default to local file store so evaluation works without a running MLflow server.
    mlflow_tracking_uri: str = "file:./mlruns"
    mlflow_experiment_name: str = "labellens-rag"
    mlflow_registered_model_name: str = "labellens-rag-pipeline"

    pipeline_version: str = "0.1.0"
    prompt_template_version: str = "v1"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _strip_origins(cls, value: str) -> str:
        return value.strip() if isinstance(value, str) else value

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
