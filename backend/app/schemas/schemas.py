"""
DocAgent v2 — Pydantic Schemas
"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field, ConfigDict


# ─── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: "UserResponse"

class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    email: Optional[str]
    role: str
    client_id: Optional[str]
    is_active: bool

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=200)
    email: Optional[str] = None
    password: str = Field(..., min_length=6)
    role: str = Field(default="client", pattern="^(admin|client)$")
    client_id: Optional[str] = None

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None
    client_id: Optional[str] = None
    is_active: Optional[bool] = None


# ─── Jobs ─────────────────────────────────────────────────────────────────────

class JobStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    total_docs: int
    successful: int
    failed: int
    needs_review: int
    client_id: str
    input_source: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    total_time_sec: float
    output_file: Optional[str]
    error_message: Optional[str]

class JobListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    total_docs: int
    successful: int
    failed: int
    needs_review: int
    client_id: str
    input_source: str
    created_at: datetime
    completed_at: Optional[datetime]
    total_time_sec: float


# ─── Documents ────────────────────────────────────────────────────────────────

class DocumentResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    id: int
    job_id: int
    filename: str
    document_type: Optional[str]
    overall_confidence: Optional[str]
    extracted_data: Optional[dict]
    validation_errors: Optional[str]
    validation_warnings: Optional[str]
    needs_review: bool
    reviewed: bool
    reviewed_by: Optional[str]
    model_used: Optional[str]
    tokens_used: int
    latency_ms: float
    created_at: datetime

class DocumentUpdateRequest(BaseModel):
    extracted_data: dict


# ─── Templates ────────────────────────────────────────────────────────────────

class TemplateColumn(BaseModel):
    """A single column in a template."""
    name: str                                              # Free-form label e.g. "Vendor Name"
    type: str = "Text"                                     # Text | Number | Date | Currency
    order: int = 0                                         # Position (0-based)
    extraction_type: str = "header"                        # "header" | "lineitem"
    # header   = extracted ONCE per document (Invoice #, Vendor, Total)
    # lineitem = extracted for EVERY row (SKU, Price, Qty, Item Description)


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    document_type: str = "invoice"
    description: Optional[str] = None
    columns: list[TemplateColumn]
    is_shared: bool = False


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    document_type: Optional[str] = None
    columns: Optional[list[TemplateColumn]] = None
    is_shared: Optional[bool] = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    document_type: str
    description: Optional[str]
    columns: list[TemplateColumn]
    is_default: bool
    is_shared: bool
    created_at: datetime


# ─── Export ───────────────────────────────────────────────────────────────────

class ExportRequest(BaseModel):
    job_id: int
    template_id: Optional[int] = None
    selected_columns: Optional[list[str]] = None
    column_order: Optional[list[str]] = None
    doc_types: Optional[list[str]] = None
    include_line_items: bool = True
    include_needs_review_only: bool = False

class ExportPerFileRequest(BaseModel):
    job_id: int
    template_id: Optional[int] = None
    selected_columns: Optional[list[str]] = None
    doc_ids: Optional[list[int]] = None


# ─── Schemas (YAML) ───────────────────────────────────────────────────────────

class SchemaResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    client_id: str
    client_name: str
    document_types: list[str]
    created_at: datetime
    updated_at: datetime

class SchemaDetailResponse(SchemaResponse):
    yaml_content: str


# ─── Drive ────────────────────────────────────────────────────────────────────

class DriveFolder(BaseModel):
    id: str
    name: str
    path: Optional[str] = None

class DriveFile(BaseModel):
    id: str
    name: str
    mime_type: str
    size: int
    modified_time: Optional[str]
    is_supported: bool

class DriveFolderContents(BaseModel):
    folders: list[DriveFolder]
    files: list[DriveFile]
    total_files: int
    supported_files: int

class DriveAuthStatus(BaseModel):
    is_configured: bool
    is_authenticated: bool
    auth_url: Optional[str] = None


# ─── Watch Folders ────────────────────────────────────────────────────────────

class WatchFolderCreate(BaseModel):
    folder_id: str
    folder_name: str
    folder_path: Optional[str] = None
    client_id: str
    auto_upload_results: bool = True
    poll_interval_minutes: int = Field(default=5, ge=1, le=60)

class WatchFolderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    folder_id: str
    folder_name: str
    client_id: str
    is_active: bool
    last_checked: Optional[datetime]
    last_file_count: int
    auto_upload_results: bool
    poll_interval_minutes: int
    created_at: datetime


# ─── Admin / Stats ────────────────────────────────────────────────────────────

class SystemStats(BaseModel):
    total_jobs: int
    total_documents: int
    total_users: int
    documents_reviewed: int
    documents_pending_review: int
    high_confidence_docs: int
    jobs_last_7_days: int

class ExtractUploadResponse(BaseModel):
    job_id: int
    message: str
    total_files: int
    status: str = "processing"
