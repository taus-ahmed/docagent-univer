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

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("docagent")


# ─── Lifespan ─────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup + shutdown tasks."""
    logger.info(f"Starting DocAgent v{settings.APP_VERSION} ({settings.ENVIRONMENT})")

    # Initialize database + create tables
    init_db()
    logger.info("Database initialized")

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
            logger.warning("⚠ CHANGE THE DEFAULT ADMIN PASSWORD BEFORE PRODUCTION DEPLOY!")
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

        # Save to filesystem
        from app.core.storage import get_storage
        storage = get_storage()
        storage.save_schema(yaml_text, parsed["client_id"])

        # Save to DB
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


# ─── App Factory ──────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="DocAgent API",
        description="AI-powered document extraction SaaS",
        version=settings.APP_VERSION,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Global Exception Handler ───────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # ── Routes ────────────────────────────────────────────────────────────────
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

    # ── Health Check ──────────────────────────────────────────────────────────
    @app.get("/health")
    def health():
        return {"status": "ok", "version": settings.APP_VERSION, "env": settings.ENVIRONMENT}

    @app.get("/")
    def root():
        return {"name": "DocAgent API", "version": settings.APP_VERSION, "docs": "/docs"}

    return app


app = create_app()