from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "GateKeep RAG"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://gatekeep:gatekeep@localhost:5432/gatekeep"
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "gatekeep_chunks"
    qdrant_vector_size: int = 384
    vector_backend: str = "memory"
    persistence_backend: str = "memory"
    rate_limit_per_minute: int = 60
    login_max_attempts: int = 5
    login_window_seconds: int = 300
    upload_max_bytes: int = 10_000_000
    jwt_secret: str = "change-me-in-development"
    jwt_expire_minutes: int = 30
    llm_provider: str = "mock"
    embedding_provider: str = "hash"
    log_raw_queries: bool = False

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", case_sensitive=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
