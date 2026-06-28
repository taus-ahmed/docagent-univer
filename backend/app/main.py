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

    logger.info("DocAgent ready.")
    yield

    logger.info("DocAgent shutting down.")


def _run_migrations():
    """
    Safe startup migrations — adds missing columns without breaking existing data.
    Uses ADD COLUMN IF NOT EXISTS so it's idempotent — safe to run every boot.
    """
    from app.models import SessionLocal
    from sqlalchemy import text

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

            # Gemini-based template understanding computed once at save time.
            # TEXT (not JSONB) for SQLite/PostgreSQL parity — matches the codebase
            # convention of storing JSON as TEXT (extraction_json, columns_json).
            """ALTER TABLE column_templates
               ADD COLUMN IF NOT EXISTS cell_binding_map TEXT""",
        ]

        for sql in migrations:
            try:
                db.execute(text(sql))
                db.commit()
            except Exception as e:
                db.rollback()
                # Log but don't crash — column may already exist in some DB flavours
                # that don't support IF NOT EXISTS syntax
                logger.debug(f"Migration skipped (likely already applied): {e}")

        logger.info("Database migrations applied")

        # FIX 7 — clear cell_binding_map that was incorrectly stored for STRUCTURAL
        # templates (e.g. BS Luq before the save-time structural guard existed). The
        # signature of a mis-analyzed structural template is a CBM with < 5 single
        # cells AND no tables. Done in Python (parse the TEXT JSON) so it works on
        # both SQLite and PostgreSQL. Runs once per boot; idempotent.
        try:
            import json as _json
            from app.models.models import ColumnTemplate
            rows = (db.query(ColumnTemplate)
                      .filter(ColumnTemplate.cell_binding_map.isnot(None)).all())
            cleared = 0
            for t in rows:
                try:
                    cbm = _json.loads(t.cell_binding_map)
                except Exception:
                    continue
                if not isinstance(cbm, dict):
                    continue
                ec = cbm.get("extract_cells") if isinstance(cbm.get("extract_cells"), dict) else {}
                tb = cbm.get("tables") if isinstance(cbm.get("tables"), list) else []
                if len(ec) < 5 and len(tb) == 0:
                    t.cell_binding_map = None
                    cleared += 1
            if cleared:
                db.commit()
                logger.info(f"Cleared {cleared} incorrect CBM(s) from structural templates")
        except Exception as e:
            db.rollback()
            logger.warning(f"CBM cleanup skipped: {e}")

    except Exception as e:
        logger.warning(f"Migration error: {e}")
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

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
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
