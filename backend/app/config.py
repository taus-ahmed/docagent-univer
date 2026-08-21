"""
DocAgent v2 â€” Configuration
Pydantic-settings based config. All values come from environment variables or .env file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Every shipped placeholder for SECRET_KEY. They differ between config.py and
# .env.example, so both are listed rather than compared against one constant —
# a guard that only knows one of them is a guard with a hole in it.
_PLACEHOLDER_SECRETS = frozenset({
    "change-me-in-production-use-openssl-rand-hex-32",
    "change-me-use-openssl-rand-hex-32",
    "changeme",
    "secret",
    "your-secret-key-here",
})


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # â”€â”€ App â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    APP_NAME: str = "DocAgent"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    ENVIRONMENT: str = "development"  # development | staging | production

    # â”€â”€ Auth â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

    # â”€â”€ Database â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    DATABASE_URL: str = "postgresql://docagent:docagent@localhost:5432/docagent"
    # Fallback for dev without Postgres:
    # DATABASE_URL: str = "sqlite:///./storage/docagent.db"

    # â”€â”€ LLM â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    GROQ_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    # Gemini, not Groq: every Groq model this codebase configures is
    # decommissioned and the account is offered no vision model at all, so
    # "groq" is a default that cannot extract anything. Production already
    # overrides it; this makes a fresh checkout work too.
    PRIMARY_LLM: str = "gemini"

    GROQ_CLASSIFICATION_MODEL: str = "llama-3.2-11b-vision-preview"
    GROQ_EXTRACTION_MODEL: str = "llama-3.3-70b-versatile"
    GROQ_VISION_MODEL: str = "llama-3.2-90b-vision-preview"
    GEMINI_MODEL: str = "gemini-2.5-flash"  # 2.0-flash retired (404); use a live model

    BATCH_SIZE: int = 5
    RATE_LIMIT_DELAY: float = 2.0
    MAX_RETRIES: int = 3

    # â”€â”€ File Storage â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
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

    # â”€â”€ Redis / Celery (Phase 4) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # â”€â”€ CORS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Accepts either name. Production sets CORS_ORIGINS; the codebase has
    # always declared ALLOWED_ORIGINS, and pydantic's extra="ignore" meant the
    # mismatch was silent — the variable looked set and did nothing.
    #
    # Typed as a plain STRING on purpose. pydantic-settings JSON-decodes a
    # list-typed field straight from the environment, BEFORE any validator
    # runs, so `CORS_ORIGINS=https://app.example.com` raises SettingsError at
    # import and the service never boots. Parsing happens in `cors_origins`.
    ALLOWED_ORIGINS: str = Field(
        default="*",
        validation_alias=AliasChoices("ALLOWED_ORIGINS", "CORS_ORIGINS"),
    )

    @property
    def cors_origins(self) -> list[str]:
        """Allowed origins as a list. Accepts a JSON array, a comma-separated
        string, or a single origin. Never raises: a malformed value falls back
        to the permissive default rather than stopping the service."""
        raw = (self.ALLOWED_ORIGINS or "").strip()
        if not raw:
            return ["*"]
        if raw.startswith("["):
            try:
                import json as _json
                parsed = _json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    return [str(x).strip() for x in parsed if str(x).strip()]
            except Exception:
                pass
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        return parts or ["*"]

    # â”€â”€ File Limits â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Accepts either name, for the same reason as ALLOWED_ORIGINS above:
    # production sets MAX_FILE_SIZE_MB and the code read MAX_UPLOAD_SIZE_MB, so
    # the production value was ignored and the code default happened to match.
    MAX_UPLOAD_SIZE_MB: int = Field(
        default=50,
        validation_alias=AliasChoices("MAX_UPLOAD_SIZE_MB", "MAX_FILE_SIZE_MB"),
    )
    MAX_FILES_PER_BATCH: int = 100

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @model_validator(mode="after")
    def _refuse_to_run_production_on_a_known_key(self):
        """A production deployment must not boot on a published signing key.

        SECRET_KEY signs every JWT. It has a default so that a fresh checkout
        runs, and that default is in this repository — so a production deploy
        that forgets the variable signs tokens with a key anyone can read, and
        anyone can then mint an admin token. Nothing in the app's behaviour
        would look wrong.

        This fires at import, not at request time, and only when
        ENVIRONMENT=production. Development and tests are untouched: a missing
        key there is a convenience, not a vulnerability.

        Deliberately NOT enforcing a minimum length. A short key is weaker than
        a long one, but a length rule could refuse a deployment that is
        currently working and secret, which is a worse failure than the one it
        prevents. Weak-but-secret is warned about; published is refused.
        """
        if self.ENVIRONMENT != "production":
            return self
        key = (self.SECRET_KEY or "").strip()
        if not key or key.casefold() in _PLACEHOLDER_SECRETS \
                or "change-me" in key.casefold() or "changeme" in key.casefold():
            raise ValueError(
                "SECRET_KEY is missing or is the placeholder shipped in this "
                "repository, and ENVIRONMENT=production.\n"
                "Every JWT would be signed with a key that is public, so "
                "anyone could mint an admin token.\n"
                "Set a real one:  SECRET_KEY=$(openssl rand -hex 32)"
            )
        if len(key) < 32:
            import warnings
            warnings.warn(
                f"SECRET_KEY is only {len(key)} characters. HS256 keys should "
                f"be at least 32 (openssl rand -hex 32). Not refused, because "
                f"it may be secret and in use — but it should be rotated.",
                stacklevel=2,
            )
        return self

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
