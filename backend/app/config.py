"""
DocAgent v2 — Configuration
Pydantic-settings based config. All values come from environment variables or .env file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field, field_validator, model_validator
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

ENVIRONMENTS = ("development", "staging", "production")
_ENV_ALIASES = {"dev": "development", "prod": "production"}
#: variables a hosting platform sets on every deployment. With one present an
#: UNSET ENVIRONMENT is refused: defaulting to development there would boot a
#: live deployment with every production check skipped.
_HOSTED_MARKERS = ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID",
                   "RENDER", "FLY_APP_NAME", "DYNO", "K_SERVICE")


def _hosted() -> Optional[str]:
    import os
    return next((m for m in _HOSTED_MARKERS if os.environ.get(m)), None)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # A refusal names the SETTING, never its value: without this pydantic
        # appends `input_value=` — the value, or the whole settings dict for
        # a model-level check — to every start-up error (Review-3 F8).
        hide_input_in_errors=True,
    )

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "DocAgent"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = False
    #: development | staging | production — NORMALISED once, by
    #: `_normalise_environment`; everything else reads the stored value.
    ENVIRONMENT: str = Field(default=None, validate_default=True)

    # ── Auth ──────────────────────────────────────────────────────────────────
    SECRET_KEY: str = "change-me-in-production-use-openssl-rand-hex-32"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hours

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "postgresql://docagent:docagent@localhost:5432/docagent"
    # Fallback for dev without Postgres:
    # DATABASE_URL: str = "sqlite:///./storage/docagent.db"

    # ── LLM ───────────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str = ""
    # The provider tried first, then each name in LLM_FALLBACKS (comma-
    # separated) in order. Names are the keys of `llm_router.PROVIDERS`;
    # Gemini is the only provider implemented, so the fallback list is empty.
    PRIMARY_LLM: str = "gemini"
    LLM_FALLBACKS: str = ""

    GEMINI_MODEL: str = "gemini-2.5-flash"  # 2.0-flash retired (404); use a live model

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

    # ── File Limits ───────────────────────────────────────────────────────────
    # Accepts either name, for the same reason as ALLOWED_ORIGINS above:
    # production sets MAX_FILE_SIZE_MB and the code read MAX_UPLOAD_SIZE_MB, so
    # the production value was ignored and the code default happened to match.
    MAX_UPLOAD_SIZE_MB: int = Field(
        default=50,
        validation_alias=AliasChoices("MAX_UPLOAD_SIZE_MB", "MAX_FILE_SIZE_MB"),
    )
    MAX_PDF_PAGES: int = 200
    MAX_IMAGE_PIXELS: int = 50_000_000
    MAX_FILES_PER_BATCH: int = 100

    @field_validator("MAX_UPLOAD_SIZE_MB", "MAX_PDF_PAGES",
                     "MAX_IMAGE_PIXELS", mode="before")
    @classmethod
    def _safe_positive_upload_limits(cls, value, info):
        defaults = {
            "MAX_UPLOAD_SIZE_MB": 50,
            "MAX_PDF_PAGES": 200,
            "MAX_IMAGE_PIXELS": 50_000_000,
        }
        try:
            parsed = int(value)
            return parsed if parsed > 0 else defaults[info.field_name]
        except (TypeError, ValueError):
            return defaults[info.field_name]

    # ── Demo accounts ─────────────────────────────────────────────────────────
    # A comma-separated list of client_ids that get the investor-demo
    # behaviour. EMPTY BY DEFAULT, which is what makes every demo rule OFF for
    # everyone until someone sets the variable: the gate is membership in this
    # list, read from the JWT's own client_id, never a role or a username.
    DEMO_CLIENT_IDS: str = ""
    #: Per-file upload ceiling for a demo client, in megabytes. Separate from
    #: MAX_UPLOAD_SIZE_MB, which still applies to everyone.
    DEMO_MAX_MB: int = 10
    #: How many extraction jobs a demo user may ever start, counted from the
    #: jobs already on their account. A demo is not a subscription.
    DEMO_MAX_UPLOADS: int = 20
    #: Kill switch for the demo's own upload door. TRUE by default, so the
    #: shipped behaviour is unchanged; set it false to run a demo off the
    #: sample documents alone — mid-demo, without a deploy. It does NOT touch
    #: the sample-document endpoints, and it does not apply to anyone whose
    #: client_id is not a demo tenant.
    DEMO_UPLOADS_ENABLED: bool = True
    #: Hide everything a demo account did BEFORE this moment: an ISO-8601
    #: datetime, read as UTC. Unset (the default) hides nothing, and an
    #: unparseable value is ignored with a warning rather than hiding
    #: everything or nothing in silence. It is a VIEW, not a delete: no row is
    #: touched, and a non-demo tenant never sees this filter at all.
    DEMO_HISTORY_CUTOFF: str = ""

    # ── Cost control ──────────────────────────────────────────────────────────
    #: Pages per firm per calendar month (UTC); 0 = unlimited. A firm's own
    #: schema may override it with `monthly_page_limit: N` (core/usage.py).
    TENANT_MONTHLY_PAGE_LIMIT: int = 0

    # ── Retention ─────────────────────────────────────────────────────────────
    #: Days after a job finishes before a daily task hard-deletes it (files,
    #: results; the job record stays, marked deleted). 0 = off (core/retention.py).
    DATA_RETENTION_DAYS: int = 0

    # ── Google Drive ──────────────────────────────────────────────────────────
    #: The ONE firm (client_id) the server's Google Drive credential belongs
    #: to. Drive is a single server-wide OAuth token, so whoever can browse it
    #: sees that Drive: every Drive route, Drive job and watch folder is closed
    #: to every other firm. EMPTY BY DEFAULT = Drive closed to everyone.
    DRIVE_TENANT: str = ""

    # ── Proxies ───────────────────────────────────────────────────────────────
    #: How many proxies in front of the app each APPEND one X-Forwarded-For
    #: entry (Railway's edge = 1). The login limiter trusts the entry the
    #: farthest of them appended — the N-th from the right — and ignores every
    #: entry before it, which the caller wrote. 0 = trust no header (the TCP
    #: peer). Fewer entries than N also falls back to the peer.
    TRUSTED_PROXY_COUNT: int = 1

    # ── Additional options ────────────────────────────────────────────────────
    #: Model calls the options may make per job (the written summary; the
    #: categorization fallback asks once per table). Each also counts as one
    #: page toward the firm's monthly limit (core/usage.py).
    OPTION_MAX_CALLS_PER_JOB: int = 20

    # ── Shutdown ──────────────────────────────────────────────────────────────
    #: Seconds a SIGTERM gives running jobs to finish the file they are on
    #: (app/core/lifecycle.py); also uvicorn's --timeout-graceful-shutdown.
    #: Keep it below the platform's own stop timeout.
    GRACEFUL_SHUTDOWN_SECONDS: int = 60

    # ── Logs ──────────────────────────────────────────────────────────────────
    #: "text" (default) or "json" — one JSON object per line for a log drain
    #: (app/core/observability.py). Every record carries the request id.
    LOG_FORMAT: str = "text"

    @property
    def max_upload_bytes(self) -> int:
        return self.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    @field_validator("ENVIRONMENT", mode="before")
    @classmethod
    def _normalise_environment(cls, v):
        """ONE spelling of ENVIRONMENT, decided here (Review-3 F8).

        `Production` and ` production ` passed the strict checks — which
        lower-cased and stripped their own copy — while `is_production` and
        the HSTS header compared the raw string, so a deployment could be
        validated as production and then serve as something else. The value
        is stripped and lower-cased once, `dev`/`prod` are spelled out, and
        the normalised value is what is stored.

        Unknown values refuse to start (the value is never echoed: a mistyped
        variable can hold anything). Unset or empty means development on a
        workstation, and refuses to start on a hosting platform."""
        env = "" if v is None else str(v).strip().lower()
        env = _ENV_ALIASES.get(env, env)
        if not env:
            marker = _hosted()
            if marker:
                raise ValueError(
                    f"ENVIRONMENT is not set, and this is a hosted deployment "
                    f"({marker} is set): set ENVIRONMENT to production or staging "
                    f"(or development, deliberately). See docs/ENVIRONMENTS.md.")
            return "development"
        if env not in ENVIRONMENTS:
            raise ValueError(f"ENVIRONMENT must be development, staging or production "
                             f"(got an unknown value of {len(env)} characters)")
        return env

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @model_validator(mode="after")
    def _validate_for_environment(self):
        """FAIL FAST on a deployment that is missing something it needs
        (Part 2.4). ENVIRONMENT selects strictness:

          development (alias dev)  nothing refused — a fresh checkout runs
          staging, production      every rule below; one message lists every
                                   problem, naming the SETTING, never its value

        Rules: SECRET_KEY at least 32 characters and not a shipped
        placeholder; DATABASE_URL set, not SQLite and not the shipped
        localhost default; STORAGE_BACKEND=s3 needs S3_BUCKET and both
        credentials; the primary model provider's key (gemini) set; explicit
        CORS origins (not empty, not "*"); TRUSTED_PROXY_COUNT between 0 and 5.
        Local storage in production is WARNED, not refused: it works, and loses
        uploads at every deploy (docs/OPERATIONS.md).

        DECISION (Part 2.4): the key length is now enforced in staging and
        production, reversing the earlier warn-only choice — check the live
        key's length before deploying (docs/RELEASE-CHECKLIST.md)."""
        env = self.ENVIRONMENT                   # normalised by its validator
        if env == "development":
            return self
        problems = []
        key = (self.SECRET_KEY or "").strip()
        if len(key) < 32 or key.casefold() in _PLACEHOLDER_SECRETS \
                or "change" in key.casefold():
            problems.append("SECRET_KEY must be at least 32 characters and not a "
                            "placeholder (openssl rand -hex 32)")
        db = (self.DATABASE_URL or "").strip()
        if not db or db.startswith("sqlite") or "localhost" in db or "127.0.0.1" in db:
            problems.append("DATABASE_URL must point at the deployment's PostgreSQL "
                            "(not SQLite, not localhost)")
        if (self.STORAGE_BACKEND or "local") == "s3":
            missing = [n for n in ("S3_BUCKET", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
                       if not str(getattr(self, n, "") or "").strip()]
            if missing:
                problems.append("STORAGE_BACKEND=s3 needs " + ", ".join(missing))
        elif env == "production":
            import warnings
            warnings.warn("STORAGE_BACKEND=local in production: uploaded files are "
                          "lost at every deploy (docs/OPERATIONS.md)", stacklevel=2)
        if str(self.PRIMARY_LLM or "gemini").strip().lower() == "gemini" \
                and not str(self.GEMINI_API_KEY or "").strip():
            problems.append("GEMINI_API_KEY must be set (PRIMARY_LLM=gemini)")
        origins = (self.ALLOWED_ORIGINS or "").strip()
        if not origins or origins == "*" or "*" in [o.strip() for o in origins.split(",")]:
            problems.append("ALLOWED_ORIGINS (or CORS_ORIGINS) must list the frontend's "
                            "origin(s) explicitly")
        names = {str(self.PRIMARY_LLM or "").strip().lower()} | {
            n.strip().lower() for n in str(self.LLM_FALLBACKS or "").split(",")}
        if "stub" in names:
            problems.append("PRIMARY_LLM/LLM_FALLBACKS names the 'stub' provider, "
                            "which is for development only")
        try:
            tpc = int(self.TRUSTED_PROXY_COUNT)
        except (TypeError, ValueError):
            tpc = -1
        if not 0 <= tpc <= 5:
            problems.append("TRUSTED_PROXY_COUNT must be a whole number from 0 to 5")
        if problems:
            raise ValueError(f"ENVIRONMENT={env} cannot start:\n  - " + "\n  - ".join(problems)
                             + "\nSee docs/ENVIRONMENTS.md.")
        return self

    @model_validator(mode="after")
    def _refuse_stub_outside_development(self):
        """The fake model provider (PRIMARY_LLM / LLM_FALLBACKS = stub,
        engine/connectors/stub_client.py) answers from the document text with
        no model at all. It exists for offline demos and UI tests; in staging
        or production it would hand clients made-up extractions, so the app
        refuses to start (Part A1)."""
        names = {str(self.PRIMARY_LLM or "").strip().lower()} | {
            n.strip().lower() for n in str(self.LLM_FALLBACKS or "").split(",")}
        env = self.ENVIRONMENT
        if "stub" in names and env in ("staging", "production"):
            raise ValueError(
                "PRIMARY_LLM/LLM_FALLBACKS names the 'stub' provider, which is "
                f"for development only, and ENVIRONMENT={env}. Remove it.")
        return self

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
        if not self.is_production:
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
