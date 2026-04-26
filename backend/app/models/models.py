"""
DocAgent v2 — Database Models (PostgreSQL + SQLAlchemy 2.0)
Full production schema with proper relationships, indexes, and JSON columns.
"""

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Column, DateTime, Float, ForeignKey,
    Integer, String, Text, Index, JSON,
    create_engine, event,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker, Session
from sqlalchemy.pool import NullPool

from app.config import settings


class Base(DeclarativeBase):
    pass


# ─── Models ───────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    display_name = Column(String(200), nullable=False)
    email = Column(String(300), unique=True, nullable=True, index=True)
    password_hash = Column(String(300), nullable=False)
    role = Column(String(20), default="client", nullable=False)  # admin | client
    client_id = Column(String(100), nullable=True, index=True)   # links to YAML schema
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)

    # Relationships
    jobs = relationship("ExtractionJob", back_populates="user", lazy="select")
    templates = relationship("ColumnTemplate", back_populates="user", lazy="select")
    watch_folders = relationship("WatchFolder", back_populates="user", lazy="select")


class ExtractionJob(Base):
    __tablename__ = "extraction_jobs"
    __table_args__ = (
        Index("ix_jobs_user_created", "user_id", "created_at"),
        Index("ix_jobs_status", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    client_id = Column(String(100), nullable=False, index=True)
    status = Column(String(20), default="pending", nullable=False)
    # pending | processing | completed | failed | cancelled

    total_docs = Column(Integer, default=0)
    successful = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    needs_review = Column(Integer, default=0)

    input_source = Column(String(50), default="upload")  # upload | drive | folder
    input_folder = Column(String(500), nullable=True)    # Drive folder ID or local path
    output_file = Column(String(500), nullable=True)     # S3 key or local path
    output_s3_key = Column(String(500), nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    total_time_sec = Column(Float, default=0.0)

    # Job metadata
    schema_id = Column(String(100), nullable=True)       # which YAML schema was used
    llm_provider = Column(String(20), nullable=True)     # groq | gemini
    notes = Column(Text, default="")
    error_message = Column(Text, nullable=True)

    # Relationships
    user = relationship("User", back_populates="jobs")
    documents = relationship("DocumentResult", back_populates="job", lazy="select",
                             cascade="all, delete-orphan")

    @property
    def success_rate(self) -> float:
        if self.total_docs == 0:
            return 0.0
        return self.successful / self.total_docs


class DocumentResult(Base):
    __tablename__ = "document_results"
    __table_args__ = (
        Index("ix_docs_job_id", "job_id"),
        Index("ix_docs_needs_review", "needs_review", "reviewed"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(Integer, ForeignKey("extraction_jobs.id", ondelete="CASCADE"),
                    nullable=False, index=True)

    filename = Column(String(500), nullable=False)
    document_type = Column(String(100), nullable=True, index=True)
    overall_confidence = Column(String(20), nullable=True)  # high | medium | low

    # Stored as JSON string for broad compatibility
    extraction_json = Column(Text, nullable=True)

    # Validation
    validation_errors = Column(Text, default="")
    validation_warnings = Column(Text, default="")
    needs_review = Column(Boolean, default=False, index=True)
    reviewed = Column(Boolean, default=False)
    reviewed_by = Column(String(100), nullable=True)
    reviewed_at = Column(DateTime, nullable=True)

    # LLM metadata
    model_used = Column(String(100), nullable=True)
    tokens_used = Column(Integer, default=0)
    latency_ms = Column(Float, default=0.0)
    classification_latency_ms = Column(Float, default=0.0)
    extraction_latency_ms = Column(Float, default=0.0)

    # File storage
    s3_key = Column(String(500), nullable=True)  # original file in S3

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    job = relationship("ExtractionJob", back_populates="documents")

    def get_extracted_data(self) -> dict:
        if not self.extraction_json:
            return {}
        try:
            return json.loads(self.extraction_json)
        except Exception:
            return {}

    def set_extracted_data(self, data: dict):
        self.extraction_json = json.dumps(data, default=str)


class ColumnTemplate(Base):
    __tablename__ = "column_templates"
    __table_args__ = (
        Index("ix_templates_user_doctype", "user_id", "document_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    name = Column(String(200), nullable=False)
    document_type = Column(String(100), default="invoice", nullable=False)
    description = Column(String(500), nullable=True)

    # JSON arrays
    columns_json = Column(Text, nullable=False)       # ["field1", "field2", ...]
    column_order_json = Column(Text, nullable=True)   # explicit ordering

    is_default = Column(Boolean, default=False)       # visible to all users
    is_shared = Column(Boolean, default=False)        # shared within client org

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="templates")

    def get_columns(self) -> list[str]:
        try:
            return json.loads(self.columns_json)
        except Exception:
            return []

    def get_column_order(self) -> list[str] | None:
        if not self.column_order_json:
            return None
        try:
            return json.loads(self.column_order_json)
        except Exception:
            return None


class WatchFolder(Base):
    __tablename__ = "watch_folders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    # Drive folder info
    folder_id = Column(String(200), nullable=False)
    folder_name = Column(String(500), nullable=False)
    folder_path = Column(String(1000), nullable=True)  # breadcrumb path

    client_id = Column(String(100), nullable=False, index=True)
    is_active = Column(Boolean, default=True, nullable=False)

    # Polling state
    last_checked = Column(DateTime, nullable=True)
    last_file_count = Column(Integer, default=0)
    processed_file_ids = Column(Text, default="[]")   # JSON list of Drive file IDs

    # Auto-processing config
    auto_upload_results = Column(Boolean, default=True)
    poll_interval_minutes = Column(Integer, default=5)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    user = relationship("User", back_populates="watch_folders")

    def get_processed_ids(self) -> list[str]:
        try:
            return json.loads(self.processed_file_ids or "[]")
        except Exception:
            return []

    def set_processed_ids(self, ids: list[str]):
        self.processed_file_ids = json.dumps(ids)


class ClientSchema(Base):
    """Tracks uploaded YAML schemas in the database."""
    __tablename__ = "client_schemas"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String(100), unique=True, nullable=False, index=True)
    client_name = Column(String(200), nullable=False)
    yaml_content = Column(Text, nullable=False)   # raw YAML stored in DB
    s3_key = Column(String(500), nullable=True)   # also stored in S3 for download
    document_types = Column(Text, nullable=True)  # JSON list of type names
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)


# ─── Database Engine ──────────────────────────────────────────────────────────

def create_db_engine(database_url: str = None):
    url = database_url or settings.DATABASE_URL

    if url.startswith("sqlite"):
        # SQLite dev config
        from sqlalchemy import event as sa_event
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @sa_event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, conn_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
    else:
        # PostgreSQL production config
        engine = create_engine(
            url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,
            pool_recycle=3600,
        )

    return engine


engine = create_db_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency for DB session injection."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
