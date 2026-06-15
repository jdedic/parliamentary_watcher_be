from pathlib import Path

from pydantic import AnyHttpUrl, field_validator
from pydantic_settings import BaseSettings

# Absolute path to the project root (three levels up from app/core/config.py).
# Used to resolve relative paths regardless of CWD.
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application configuration loaded from environment variables."""

    # Database
    database_url: str

    # External API
    tweede_kamer_base_url: AnyHttpUrl = (
        "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0"
    )

    # Auth
    api_key: str

    # OpenAI
    openai_api_key: str
    openai_model: str = "gpt-4.1-mini"
    openai_generation_model: str = "gpt-4.1"
    openai_embedding_model: str = "text-embedding-3-large"

    # Qdrant
    qdrant_url: str
    qdrant_api_key: str = ""
    qdrant_collection: str = "plenary_chunks"

    # Storage
    xml_storage_path: str = "storage/xml_files"

    @field_validator("xml_storage_path", mode="before")
    @classmethod
    def _resolve_xml_storage_path(cls, v: str) -> str:
        p = Path(v)
        return str(p if p.is_absolute() else BASE_DIR / p)
    
    eval_run_id: str = ""      # Empty = auto "live_{YYYYMMDD}"; set to e.g. "benchmark_001" for named runs

    sync_limit: int = 2        # Number of vergaderings with Eindpublicatie to sync
    sync_batch_size: int = 30  # Vergaderings fetched per API page while searching
    sync_interval_minutes: int = 720  # How often the background sync runs
    # CORS
    allowed_origins: list[str] = [
        "http://localhost:4200",
        "https://parlai.up.railway.app",
    ]

    # Rate limiting
    chat_rate_limit: str = "20/minute"

    # Logging
    log_level: str = "INFO"
    environment: str = "development"  # "production" enables JSON logging

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
