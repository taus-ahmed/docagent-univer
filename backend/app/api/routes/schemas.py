"""
DocAgent v2 — Schema Routes
GET    /api/schemas           — list all schemas
POST   /api/schemas           — upload new YAML schema
GET    /api/schemas/{id}      — get schema detail with YAML content
PUT    /api/schemas/{id}      — update schema
DELETE /api/schemas/{id}      — delete schema
"""

import json
from datetime import datetime
from pathlib import Path

import yaml
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_admin
from app.core.storage import get_storage
from app.models import get_db, User, ClientSchema
from app.schemas.schemas import SchemaResponse, SchemaDetailResponse

router = APIRouter(prefix="/api/schemas", tags=["schemas"])


@router.get("", response_model=list[SchemaResponse])
def list_schemas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all active client schemas."""
    schemas = db.query(ClientSchema).filter(ClientSchema.is_active == True).all()
    return [_to_response(s) for s in schemas]


@router.post("", response_model=SchemaResponse, status_code=201)
async def upload_schema(
    file: UploadFile = File(..., description="YAML schema file"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage=Depends(get_storage),
):
    """Upload a new client YAML schema."""
    if not file.filename.endswith((".yaml", ".yml")):
        raise HTTPException(status_code=400, detail="File must be .yaml or .yml")

    content = await file.read()
    yaml_text = content.decode("utf-8")

    # Parse and validate YAML
    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML: {e}")

    client_id = parsed.get("client_id")
    client_name = parsed.get("client_name")
    if not client_id or not client_name:
        raise HTTPException(
            status_code=400,
            detail="YAML must have 'client_id' and 'client_name' fields",
        )

    doc_types = list(parsed.get("document_types", {}).keys())

    # Save to filesystem
    local_path, key = storage.save_schema(yaml_text, client_id)

    # Upsert in database
    existing = db.query(ClientSchema).filter(ClientSchema.client_id == client_id).first()
    if existing:
        existing.client_name = client_name
        existing.yaml_content = yaml_text
        existing.s3_key = key
        existing.document_types = json.dumps(doc_types)
        existing.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(existing)
        return _to_response(existing)
    else:
        schema = ClientSchema(
            client_id=client_id,
            client_name=client_name,
            yaml_content=yaml_text,
            s3_key=key,
            document_types=json.dumps(doc_types),
            created_by=current_user.id,
        )
        db.add(schema)
        db.commit()
        db.refresh(schema)
        return _to_response(schema)


@router.get("/{client_id}", response_model=SchemaDetailResponse)
def get_schema(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get schema details including raw YAML."""
    schema = db.query(ClientSchema).filter(
        ClientSchema.client_id == client_id,
        ClientSchema.is_active == True,
    ).first()

    if not schema:
        raise HTTPException(status_code=404, detail=f"Schema '{client_id}' not found")

    return SchemaDetailResponse(
        id=schema.id,
        client_id=schema.client_id,
        client_name=schema.client_name,
        document_types=json.loads(schema.document_types or "[]"),
        created_at=schema.created_at,
        updated_at=schema.updated_at,
        yaml_content=schema.yaml_content,
    )


@router.delete("/{client_id}")
def delete_schema(
    client_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
):
    """Soft-delete a schema (admin only)."""
    schema = db.query(ClientSchema).filter(ClientSchema.client_id == client_id).first()
    if not schema:
        raise HTTPException(status_code=404, detail="Schema not found")

    schema.is_active = False
    db.commit()
    return {"message": f"Schema '{client_id}' deleted"}


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _to_response(s: ClientSchema) -> SchemaResponse:
    return SchemaResponse(
        id=s.id,
        client_id=s.client_id,
        client_name=s.client_name,
        document_types=json.loads(s.document_types or "[]"),
        created_at=s.created_at,
        updated_at=s.updated_at,
    )
