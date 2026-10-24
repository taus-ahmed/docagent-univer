"""
DocAgent v2 — Schema Routes
GET    /api/schemas           — the schemas this user may see
POST   /api/schemas           — upload new YAML schema (ADMIN)
GET    /api/schemas/{id}      — get schema detail with YAML content (own tenant)
PUT    /api/schemas/{id}      — update schema
DELETE /api/schemas/{id}      — delete schema
"""

import json
from datetime import datetime

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_admin
from app.core.storage import get_storage
from app.models import get_db, User, ClientSchema
from app.schemas.schemas import SchemaResponse, SchemaDetailResponse

router = APIRouter(prefix="/api/schemas", tags=["schemas"])


def _may_see_all_schemas(current_user: User) -> bool:
    """Only a super-admin — role=admin with NO tenant of their own.

    This is the same test the rest of the app uses for "sees everything"
    (`extract.py::_get_job_or_404`, `templates.py::_get_template_or_403`), and
    a tenanted admin is deliberately scoped to their own client here: they have
    a tenant, their own schema is the one they administer, and a schema is the
    one object in this app that carries another company's field vocabulary.
    """
    return current_user.role == "admin" and not current_user.client_id


@router.get("", response_model=list[SchemaResponse])
def list_schemas(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The active schemas this user may see — their own tenant's, unless they
    are a super-admin.

    This used to return EVERY tenant's schema to any authenticated user: the
    client_id, the company name and the document types of every other customer
    on the deployment.

    ⚠ The Extract page reads `schemas[0].client_id` to fill the upload form, so
    this list is load-bearing for ordinary use, not just informational. It
    still works: a tenanted user now gets their own schema first because it is
    the only one they get. A user with NO schema gets `[]`, which the page
    already handles (it falls back to "demo_001"), and the upload endpoint
    ignores the form value anyway — `resolve_client_id` takes the tenant from
    the token.
    """
    q = db.query(ClientSchema).filter(ClientSchema.is_active == True)
    if not _may_see_all_schemas(current_user):
        q = q.filter(ClientSchema.client_id == current_user.client_id)
    return [_to_response(s) for s in q.all()]


@router.post("", response_model=SchemaResponse, status_code=201)
async def upload_schema(
    file: UploadFile = File(..., description="YAML schema file"),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin),
    storage=Depends(get_storage),
):
    """Upload a new client YAML schema. ADMIN ONLY.

    This endpoint keys on the `client_id` INSIDE the uploaded YAML and
    overwrites the existing row for that client (see below), so as an
    authenticated-user endpoint it let any user replace any other tenant's
    extraction vocabulary — a cross-tenant WRITE, not merely a read. There is
    no per-tenant upload story that needs this: schemas are provisioned.
    """
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
    if (not _may_see_all_schemas(current_user)
            and client_id != current_user.client_id):
        raise HTTPException(
            status_code=404,
            detail=f"Schema '{client_id}' not found",
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
    """Get schema details including raw YAML — own tenant only.

    The raw YAML is another company's field vocabulary, document types and
    naming, and this endpoint handed it to any authenticated user who could
    guess or read a client_id (the list endpoint above printed them all).

    A tenant the caller may not read answers 404, WORD FOR WORD the same as a
    client_id that does not exist. A 403 here would confirm which other
    companies are on the deployment, which is most of what the leak was worth.
    """
    schema = db.query(ClientSchema).filter(
        ClientSchema.client_id == client_id,
        ClientSchema.is_active == True,
    ).first()

    if not schema or not (_may_see_all_schemas(current_user)
                          or schema.client_id == current_user.client_id):
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
    query = db.query(ClientSchema).filter(ClientSchema.client_id == client_id)
    if not _may_see_all_schemas(current_user):
        query = query.filter(ClientSchema.client_id == current_user.client_id)
    schema = query.first()
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
