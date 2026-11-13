from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]

class Settings(BaseSettings):
    app_name: str = "Your Flight Support Bot System"
    app_env: str = "development"
    llm_provider: Literal["ollama", "openai"] = "ollama"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_embedding_model: str = "text-embedding-3-small"
    pinecone_api_key: str = ""
    pinecone_index_name: str = "fde-it-support-nomic-768"
    pinecone_namespace: str = "tunisair-fr"
    embedding_provider: Literal["ollama", "openai"] = "ollama"
    embedding_model: str = "nomic-embed-text"
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2"
    cors_origins: list[str] = Field(default_factory=list)
    top_k: int = 4
    max_retries: int = 1
    audit_db_path: str = str(BASE_DIR / "data" / "audit.db")
    tunisair_crawl_delay_seconds: float = 1.0
    tunisair_request_timeout_seconds: int = 20
    tunisair_sync_manifest_path: str = str(BASE_DIR / "data" / "tunisair_sync_manifest.json")
    tunisair_content_db_path: str = str(BASE_DIR / "data" / "tunisair_content.db")

    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")




@lru_cache
def get_settings() -> Settings:
    return Settings()
