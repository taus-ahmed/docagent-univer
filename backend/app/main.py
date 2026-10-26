"""
DocAgent v2 — FastAPI Application Entry Point
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from datetime import datetime

from app.models import init_db
from app.core.auth import hash_password

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("docagent")


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown tasks."""
    logger.info(f"Starting DocAgent v{settings.APP_VERSION} ({settings.ENVIRONMENT})")

    # Initialize database + create tables
    init_db()
    logger.info("Database initialized")

    # Run safe column migrations (ADD COLUMN IF NOT EXISTS)
    _run_migrations()

    # Ensure storage directories exist
    settings.ensure_storage_dirs()
    logger.info("Storage directories ready")
    _sweep_temp_copies()

    # Provision the first administrator only when explicitly configured.
    _bootstrap_admin()

    # Copy demo schema if no schemas exist
    _seed_demo_schema()
    _materialise_schemas()

    # Nothing can still be running: this process just started
    _release_stranded_jobs()

    # Opt-in retention (DATA_RETENTION_DAYS; 0 = off, nothing started)
    from app.core.retention import start_daily_purge
    retention_stop = start_daily_purge()

    logger.info("DocAgent ready.")
    yield
    if retention_stop is not None:
        retention_stop.set()

    logger.info("DocAgent shutting down.")


def _run_migrations():
    """
    Additive startup migrations. Idempotent — safe to run every boot.

    THESE MUST FAIL LOUDLY. The previous version wrapped every statement in
    `except Exception` and logged the failure at DEBUG — invisible at
    production log level — then printed "Database migrations applied"
    whether anything had applied or not. That is how
    `column_templates.description` sat as VARCHAR(500) against an ORM that
    said Text for months: every real template save failed, the repair never
    ran, and the startup log said everything was fine.

    So now: a statement that does not apply to this dialect is SKIPPED with a
    reason, a statement that fails is an ERROR with the SQL and the exception,
    the summary line reports real counts, and in production any failure raises
    rather than serving on a schema nobody verified. On Railway that fails the
    healthcheck and the previous deployment keeps serving, which is the
    outcome you want from a migration that cannot run.
    """
    from app.models import SessionLocal
    from sqlalchemy import text

    # Every statement below is PostgreSQL syntax: ADD COLUMN IF NOT EXISTS,
    # ALTER COLUMN ... TYPE and DROP COLUMN IF EXISTS are all unsupported on
    # SQLite. On SQLite create_all() has already produced the current schema,
    # so skipping is correct — it just has to be SAID rather than swallowed.
    PG_ONLY = {"postgresql"}

    db = SessionLocal()
    try:
        migrations = [
            # Add client_id to column_templates (for multi-tenant template isolation)
            """ALTER TABLE column_templates
               ADD COLUMN IF NOT EXISTS client_id VARCHAR(100)""",

            # Add updated_at to column_templates if missing
            """ALTER TABLE column_templates
               ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP""",

            # Add last_login to users if missing
            """ALTER TABLE users
               ADD COLUMN IF NOT EXISTS last_login TIMESTAMP""",

            # Add schema_id to extraction_jobs if missing
            """ALTER TABLE extraction_jobs
               ADD COLUMN IF NOT EXISTS schema_id VARCHAR(100)""",

            # Add total_tokens to extraction_jobs for analytics
            """ALTER TABLE extraction_jobs
               ADD COLUMN IF NOT EXISTS total_tokens INTEGER DEFAULT 0""",

            # Add total_cost to extraction_jobs for analytics
            """ALTER TABLE extraction_jobs
               ADD COLUMN IF NOT EXISTS total_cost FLOAT DEFAULT 0.0""",

            # Add progress_message for live job progress updates (Issue 2)
            """ALTER TABLE extraction_jobs
               ADD COLUMN IF NOT EXISTS progress_message TEXT""",

            # FIX 5: persist the raw LLM (Gemini) response for audit / re-export / debug
            """ALTER TABLE document_results
               ADD COLUMN IF NOT EXISTS raw_llm_response TEXT""",

            # Keep the upload name separately from the engine's per-record
            # display name (for example "cheques.pdf [2 of 4]").
            """ALTER TABLE document_results
               ADD COLUMN IF NOT EXISTS original_filename VARCHAR(500)""",

            # column_templates.description holds the full spreadsheet grid as
            # JSON and can run to tens of thousands of characters. An older
            # create_all() made it VARCHAR(500); the ORM has said Text for a
            # long time, and create_all NEVER alters an existing column. Any
            # database created before that change silently rejects every real
            # template with StringDataRightTruncation — a 500 on save, and no
            # way to tell from the UI. Idempotent: a no-op where it is already
            # text (production).
            """ALTER TABLE column_templates
               ALTER COLUMN description TYPE TEXT""",

            # Derived-structure artifacts, removed. A template's shape is now
            # computed fresh from its grid on every run, so there is nothing to
            # store and nothing that can go stale. Dropping is idempotent.
            """ALTER TABLE column_templates
               DROP COLUMN IF EXISTS cell_binding_map""",
            """ALTER TABLE column_templates
               DROP COLUMN IF EXISTS shape_json""",
        ]

        dialect = db.bind.dialect.name
        applied, failures = 0, []

        if dialect not in PG_ONLY:
            logger.warning(
                "Startup migrations SKIPPED: %d statements are PostgreSQL "
                "syntax and this database is '%s'. create_all() supplies the "
                "current schema here, but no drift repair runs on this "
                "dialect.", len(migrations), dialect)
        else:
            for sql in migrations:
                label = " ".join(sql.split())[:90]
                try:
                    db.execute(text(sql))
                    db.commit()
                    applied += 1
                except Exception as e:
                    db.rollback()
                    failures.append((label, e))
                    logger.error("MIGRATION FAILED: %s\n  %s: %s",
                                 label, type(e).__name__, e)

            if failures:
                logger.error("Startup migrations: %d applied, %d FAILED",
                             applied, len(failures))
            else:
                logger.info("Startup migrations: %d applied, 0 failed", applied)

        if failures and settings.is_production:
            raise RuntimeError(
                f"{len(failures)} startup migration(s) failed and "
                f"ENVIRONMENT=production. Refusing to serve on a schema that "
                f"was not verified — the first failure was: "
                f"{failures[0][0]} -> {failures[0][1]}"
            )
        return {"dialect": dialect, "applied": applied,
                "failed": len(failures)}

    finally:
        db.close()


def _sweep_temp_copies():
    """Delete object-store temp copies a dead worker left behind: client
    documents on this container's disk. Only files older than a day, only in
    the app's own temp directory (`storage.sweep_temp_copies`). A sweep that
    fails is logged and never stops boot."""
    try:
        from app.core.storage import get_storage
        removed = get_storage().sweep_temp_copies()
        if removed:
            logger.info("Removed %d stale temp cop%s", removed, "y" if removed == 1 else "ies")
    except Exception as e:
        logger.warning("Temp copy sweep skipped (%s)", type(e).__name__)


def _release_stranded_jobs():
    """Any job left `pending`/`processing` by a dead process is FAILED.

    Extraction runs on a daemon thread, so it dies with the process — a
    deploy, a restart, an OOM kill. The job row stays `processing` for ever:
    the UI polls it every two seconds until the tab is closed, no result is
    ever written, and nothing anywhere says what happened. A hung job is worse
    than a failed one, because a failed one can be retried and a hung one
    cannot even be diagnosed.

    This runs at BOOT, which is the one moment the answer is certain: this
    process has just started, so it owns no threads, and any job still marked
    running belongs to a process that no longer exists. That is a fact about
    the world rather than a timeout guess, which is why there is no age
    threshold here.

    ⚠ Single-instance reasoning. With more than one container serving the same
    database this would fail a job another instance is genuinely working on.
    Phase 4 moves extraction to Celery, where the queue owns liveness; until
    then the deploy is one instance and this is the honest cleanup. Anyone
    scaling past one worker must remove or rework this in the same commit.
    """
    from app.models import SessionLocal
    from app.models.models import ExtractionJob

    db = SessionLocal()
    try:
        jobs = (db.query(ExtractionJob)
                .filter(ExtractionJob.status.in_(("pending", "processing"))).all())
        if not jobs:
            return
        # Each FILE is committed when it finishes (job_worker._commit_file),
        # so a job cut off mid-way may hold results for the files before the
        # one in flight. The message says which is true, and the reason
        # travels as a mark.
        from app.models.models import DocumentResult
        now = datetime.utcnow()
        for job in jobs:
            saved = (db.query(DocumentResult)
                     .filter(DocumentResult.job_id == job.id).count())
            if saved:
                msg = ("Interrupted by a server restart before it finished. "
                       f"{saved} of {job.total_docs or '?'} document result(s) "
                       "had been saved and are kept; upload the remaining "
                       "files again.")
            else:
                msg = ("Interrupted by a server restart before it finished. "
                       "Nothing was saved for this job — upload the files again.")
            job.status = "failed"
            job.error_message = msg
            job.progress_message = msg
            job.completed_at = now
            job.set_mark("status_reason", "Interrupted by restart")
        db.commit()
        logger.warning(
            "Released %d job(s) stranded by a previous restart: %s",
            len(jobs), ", ".join(str(j.id) for j in jobs[:20]))
    except Exception as e:
        db.rollback()
        # Never block boot on housekeeping.
        logger.error("Could not release stranded jobs: %s", type(e).__name__)
    finally:
        db.close()


_BOOTSTRAP_USERNAME_ENV = "DOCAGENT_BOOTSTRAP_ADMIN_USERNAME"
_BOOTSTRAP_PASSWORD_ENV = "DOCAGENT_BOOTSTRAP_ADMIN_PASSWORD"
_BOOTSTRAP_DISPLAY_NAME_ENV = "DOCAGENT_BOOTSTRAP_ADMIN_DISPLAY_NAME"
_KNOWN_BOOTSTRAP_PASSWORDS = frozenset({
    "admin",
    "admin" + "123",
    "administrator",
    "change-me",
    "change-me-in-production",
    "changeme",
    "password",
    "password123",
    "your_admin_password_here",
})


def _validate_bootstrap_password(username: str, password: str) -> None:
    """Apply the deliberately small, deterministic first-admin policy."""
    if not password or not password.strip():
        raise RuntimeError("Administrator bootstrap password must not be empty.")
    if len(password) < 15:
        raise RuntimeError(
            "Administrator bootstrap password must be at least 15 characters.")
    if password.casefold() == username.casefold():
        raise RuntimeError(
            "Administrator bootstrap password must differ from the username.")
    if password.casefold() in _KNOWN_BOOTSTRAP_PASSWORDS:
        raise RuntimeError(
            "Administrator bootstrap password is a known default or placeholder.")


def _bootstrap_admin():
    """Provision one administrator from explicit environment variables."""
    from app.models import SessionLocal
    from app.models.models import User

    db = SessionLocal()
    try:
        admin = db.query(User).filter_by(role="admin").first()
        if admin:
            active_admin = db.query(User).filter_by(
                role="admin", is_active=True).first()
            if not active_admin:
                logger.warning(
                    "Administrator lock-out risk: administrator rows exist, "
                    "but every administrator is inactive.")
            return

        username_raw = os.environ.get(_BOOTSTRAP_USERNAME_ENV)
        password_raw = os.environ.get(_BOOTSTRAP_PASSWORD_ENV)
        display_name_raw = os.environ.get(_BOOTSTRAP_DISPLAY_NAME_ENV)

        if username_raw is None and password_raw is None and display_name_raw is None:
            logger.warning(
                "No administrator exists. To provision the first administrator, "
                "set %s and %s (optionally %s), restart once, then remove %s "
                "immediately after successful bootstrap.",
                _BOOTSTRAP_USERNAME_ENV, _BOOTSTRAP_PASSWORD_ENV,
                _BOOTSTRAP_DISPLAY_NAME_ENV, _BOOTSTRAP_PASSWORD_ENV)
            return

        username = (username_raw or "").strip()
        if not username or password_raw is None:
            raise RuntimeError(
                "Administrator bootstrap configuration is incomplete: set both "
                f"{_BOOTSTRAP_USERNAME_ENV} and {_BOOTSTRAP_PASSWORD_ENV}.")

        # Deployment dashboards and secret-file tooling commonly leave a final
        # newline. It is never intended to be part of an interactive password.
        password = password_raw.strip()
        _validate_bootstrap_password(username, password)
        if db.query(User).filter_by(username=username).first():
            raise RuntimeError(
                "Administrator bootstrap username is already in use.")
        display_name = (display_name_raw or "").strip() or username
        db.add(User(
            username=username,
            display_name=display_name,
            email=None,
            password_hash=hash_password(password),
            role="admin",
            client_id=None,
            is_active=True,
        ))
        db.commit()
        logger.info(
            "Initial administrator bootstrap succeeded for username %r. "
            "Remove %s immediately.", username, _BOOTSTRAP_PASSWORD_ENV)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _materialise_schemas():
    """Write every client's YAML from the database to storage if it is missing.

    This is the bug that actually broke the deploy, and it is not about losing
    files — it is about never putting them back. A schema is stored twice: the
    text in `client_schemas.yaml_content`, and a copy on disk that
    `storage.get_schema_path()` hands to the extraction engine. On a container
    with no volume the disk copy dies at every redeploy, and `_seed_demo_schema`
    returned early whenever the TABLE was non-empty — which it always is after
    the first boot. So from the second deploy onward there was no YAML anywhere
    on disk, `get_schema_path()` returned None for every client, and
    POST /api/extract/upload answered 404 "No schema found" for every upload.

    The database copy was never lost, so nothing here is recovery — it is
    re-materialisation, and it is idempotent: schemas already present are left
    alone.
    """
    from app.models import SessionLocal
    from app.models.models import ClientSchema
    from app.core.storage import get_storage

    db = SessionLocal()
    try:
        storage = get_storage()
        restored = 0
        for row in db.query(ClientSchema).all():
            if not (row.yaml_content or "").strip():
                continue
            key = storage.schema_key(row.client_id)
            if storage.exists(key):
                continue
            try:
                storage.save_schema(row.yaml_content, row.client_id)
                restored += 1
            except Exception as e:
                logger.error("Could not materialise schema for %s: %s",
                             row.client_id, type(e).__name__)
        if restored:
            logger.info("Schemas materialised from database: %d", restored)
    except Exception as e:
        logger.warning("Schema materialisation skipped: %s", type(e).__name__)
    finally:
        db.close()


def _seed_demo_schema():
    """Copy demo_accounting.yaml to schemas dir if no schemas exist."""
    from app.models import SessionLocal
    from app.models.models import ClientSchema
    import yaml, json

    db = SessionLocal()
    try:
        count = db.query(ClientSchema).count()
        if count > 0:
            return

        demo_yaml = Path(__file__).parent.parent / "engine" / "demo_accounting.yaml"
        if not demo_yaml.exists():
            return

        yaml_text = demo_yaml.read_text()
        parsed = yaml.safe_load(yaml_text)

        from app.core.storage import get_storage
        storage = get_storage()
        storage.save_schema(yaml_text, parsed["client_id"])

        doc_types = list(parsed.get("document_types", {}).keys())
        db.add(ClientSchema(
            client_id=parsed["client_id"],
            client_name=parsed["client_name"],
            yaml_content=yaml_text,
            document_types=json.dumps(doc_types),
        ))
        db.commit()
        logger.info(f"Demo schema seeded: {parsed['client_name']}")
    except Exception as e:
        logger.warning(f"Could not seed demo schema: {type(e).__name__}")
    finally:
        db.close()


# ── App Factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="DocAgent API",
        description="AI-powered document extraction SaaS",
        version=settings.APP_VERSION,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # CORS — from configuration, not hardcoded. allow_credentials stays False
    # because the frontend authenticates with a Bearer token from localStorage,
    # not a cookie; turning it on would be a behaviour change, not a fix.
    origins = settings.cors_origins
    if origins == ["*"]:
        logger.warning("CORS: allowing ALL origins. Set CORS_ORIGINS to the "
                       "frontend URL to restrict it.")
    else:
        logger.info(f"CORS: allowing {len(origins)} configured origin(s)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Every /api/ response is one firm's data: no shared cache (a proxy, a
    # CDN, the frontend's edge) may keep it. A route that sets its own policy
    # keeps it — the page image is "private", cacheable by the viewer's own
    # browser only. Vary: Authorization in case anything caches regardless.
    @app.middleware("http")
    async def _no_shared_caching(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault("Vary", "Authorization")
        return response

    # Global Exception Handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        # Method and path only: a query string, the exception's message and a
        # full traceback can all quote a request body or a document.
        from log_safety import exc_brief, safe_traceback_text
        logger.error("Unhandled exception on %s %s: %s\n%s", request.method,
                     request.url.path, exc_brief(exc), safe_traceback_text(exc))
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # Routes
    from app.api.routes.auth import router as auth_router
    from app.api.routes.extract import router as extract_router
    from app.api.routes.export import router as export_router
    from app.api.routes.templates import router as templates_router
    from app.api.routes.schemas import router as schemas_router
    from app.api.routes.drive import router as drive_router
    from app.api.routes.admin import router as admin_router
    from app.api.routes.demo import router as demo_router
    from app.api.routes.review import router as review_router

    app.include_router(auth_router)
    app.include_router(extract_router)
    app.include_router(export_router)
    app.include_router(templates_router)
    app.include_router(schemas_router)
    app.include_router(drive_router)
    app.include_router(admin_router)
    app.include_router(demo_router)
    app.include_router(review_router)

    # Health Check
    @app.get("/health")
    def health():
        return {"status": "ok", "version": settings.APP_VERSION, "env": settings.ENVIRONMENT}

    @app.get("/")
    def root():
        return {"name": "DocAgent API", "version": settings.APP_VERSION, "docs": "/docs"}

    return app


app = create_app()
