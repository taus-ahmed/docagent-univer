"""
DocAgent v2 — Configuration
Pydantic-settings based config. All values come from environment variables or .env file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "DocAgent"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | staging | production

    # ── Auth ──────────────────────────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://docagent:docagent@localhost:5432/docagent"
    # Fallback for dev without Postgres:
    # DATABASE_URL: str = "sqlite:///./storage/docagent.db"

    # ── LLM ───────────────────────────────────────────────────────────────────
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    PRIMARY_LLM: str = "groq"

    GROQ_CLASSIFICATION_MODEL: str = "llama-3.2-11b-vision-preview"
    GROQ_EXTRACTION_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_VISION_MODEL: str = "llama-3.2-90b-vision-preview"
    GEMINI_MODEL: str = "gemini-2.0-flash"

    BATCH_SIZE: int = 5
    RATE_LIMIT_DELAY: float = 2.0
    MAX_RETRIES: int = 3

    # ── File Storage ──────────────────────────────────────────────────────────
    STORAGE_BACKEND: str = "local"  # local | s3
    LOCAL_UPLOAD_DIR: Path = Path("./storage/uploads")
    LOCAL_OUTPUT_DIR: Path = Path("./storage/outputs")
    LOCAL_SCHEMAS_DIR: Path = Path("./storage/schemas")

    # S3 / Cloudflare R2 (Phase 3+)
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: str = "us-east-1"
    S3_BUCKET: Optional[str] = None
    S3_ENDPOINT_URL: Optional[str] = None  # For Cloudflare R2

    # ── Redis / Celery (Phase 4) ───────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # ── CORS ──────────────────────────────────────────────────────────────────
    ALLOWED_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "https://docagent.vercel.app",
    ]

    # ── File Limits ───────────────────────────────────────────────────────────
    MAX_UPLOAD_SIZE_MB: int = 50
    MAX_FILES_PER_BATCH: int = 100

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    def ensure_storage_dirs(self):
        """Create local storage directories if they don't exist."""
        self.LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        self.LOCAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        self.LOCAL_SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
        Path("./storage/schemas/clients").mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
