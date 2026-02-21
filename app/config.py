from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables.

    All values come from .env file or environment. Validated at startup —
    missing required values cause an immediate error with a clear message.
    """

    # LLM
    OPENAI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    LLM_PROVIDER: Literal["openai", "claude", "ollama", "groq"] = "openai"
    LLM_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIMENSION: int = 1536

    # Database
    DATABASE_URL: str  # async driver (asyncpg)
    DATABASE_URL_SYNC: str  # sync driver (for Alembic CLI)

    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Processing
    CHUNK_SIZE: int = 500
    CHUNK_OVERLAP: int = 50
    MAX_UPLOAD_SIZE_MB: int = 20

    # App
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}
