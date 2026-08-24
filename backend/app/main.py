"""
DocAgent v2 — FastAPI Application Entry Point
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
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

    # Seed default admin if DB is empty
    _seed_admin()

    # Copy demo schema if no schemas exist
    _seed_demo_schema()
    _materialise_schemas()

    logger.info("DocAgent ready.")
    yield

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


def _seed_admin():
    """Create default admin user if none exists."""
    from app.models import SessionLocal
    from app.models.models import User
    db = SessionLocal()
    try:
        admin = db.query(User).filter_by(role="admin").first()
        if not admin:
            db.add(User(
                username="admin",
                display_name="Administrator",
                email=None,
                password_hash=hash_password("admin123"),
                role="admin",
                is_active=True,
            ))
            db.commit()
            logger.info("Default admin user created (username: admin, password: admin123)")
            logger.warning("⚠  CHANGE THE DEFAULT ADMIN PASSWORD BEFORE PRODUCTION DEPLOY!")
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
                             row.client_id, e)
        if restored:
            logger.info("Schemas materialised from database: %d", restored)
    except Exception as e:
        logger.warning("Schema materialisation skipped: %s", e)
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
        logger.warning(f"Could not seed demo schema: {e}")
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

    # Global Exception Handler
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
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

    app.include_router(auth_router)
    app.include_router(extract_router)
    app.include_router(export_router)
    app.include_router(templates_router)
    app.include_router(schemas_router)
    app.include_router(drive_router)
    app.include_router(admin_router)

    # Health Check
    @app.get("/health")
    def health():
        return {"status": "ok", "version": settings.APP_VERSION, "env": settings.ENVIRONMENT}

    @app.get("/")
    def root():
        return {"name": "DocAgent API", "version": settings.APP_VERSION, "docs": "/docs"}

    return app


app = create_app()
