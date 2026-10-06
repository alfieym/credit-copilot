"""Centralized configuration: read from environment variables / .env via pydantic-settings."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- LLM provider: default OpenAI; DeepSeek/Qwen/Zhipu via compatible endpoint;
    #     Claude via Bedrock ---
    llm_provider: str = "openai"          # openai | deepseek | qwen | zhipu | bedrock
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"

    # --- OpenAI-compatible endpoints (reused by deepseek/qwen/zhipu) ---
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-chat"
    llm_reasoner_model: str = "deepseek-reasoner"

    # --- Claude via AWS Bedrock ---
    aws_region: str = "us-east-1"
    bedrock_model: str = "anthropic.claude-3-5-sonnet-20241022-v2:0"

    # --- Embedding (OpenAI-compatible) ---
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.siliconflow.cn/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024

    # --- Postgres + pgvector ---
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "credit_copilot"
    postgres_user: str = "credit"
    postgres_password: str = "credit"

    # --- Langfuse (observability) ---
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    langfuse_host: str = "http://localhost:3000"

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
