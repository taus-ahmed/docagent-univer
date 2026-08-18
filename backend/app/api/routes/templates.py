"""
DocAgent v2 — Template Routes
GET    /api/templates          — list templates
POST   /api/templates          — create template
GET    /api/templates/{id}     — get single template
PUT    /api/templates/{id}     — update template
DELETE /api/templates/{id}     — delete template
"""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.models import get_db, User, ColumnTemplate
from app.schemas.schemas import TemplateCreate, TemplateUpdate, TemplateResponse, TemplateColumn

router = APIRouter(prefix="/api/templates", tags=["templates"])


@router.get("", response_model=list[TemplateResponse])
def list_templates(
    document_type: str = None,
    q: str = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Admin with no client_id sees everything
    if current_user.role == "admin" and not current_user.client_id:
        query = db.query(ColumnTemplate)
    else:
        # User sees:
        # 1. Their own templates
        # 2. Default system templates (is_default=True)
        # 3. Shared templates from THEIR OWN company only
        query = db.query(ColumnTemplate).filter(
            (ColumnTemplate.user_id == current_user.id)
            | (ColumnTemplate.is_default == True)
            | (
                (ColumnTemplate.is_shared == True)
                & (ColumnTemplate.client_id == current_user.client_id)
            )
        )

    if document_type:
        query = query.filter(ColumnTemplate.document_type == document_type)
    if q:
        query = query.filter(func.lower(ColumnTemplate.name).contains(q.lower()))
    return [_to_response(t) for t in query.order_by(ColumnTemplate.created_at.desc()).all()]


@router.get("/{template_id}", response_model=TemplateResponse)
def get_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tpl = db.query(ColumnTemplate).filter(ColumnTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")

    # Admin with no client_id can see all
    if current_user.role == "admin" and not current_user.client_id:
        return _to_response(tpl)

    # Owner can always see their own
    if tpl.user_id == current_user.id:
        return _to_response(tpl)

    # Shared templates only visible within same company
    if tpl.is_shared and tpl.client_id == current_user.client_id:
        return _to_response(tpl)

    # Default templates visible to all
    if tpl.is_default:
        return _to_response(tpl)

    raise HTTPException(status_code=403, detail="Access denied")


@router.post("", response_model=TemplateResponse, status_code=201)
def create_template(
    payload: TemplateCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    existing = db.query(ColumnTemplate).filter(
        ColumnTemplate.user_id == current_user.id,
        ColumnTemplate.name == payload.name,
        ColumnTemplate.document_type == payload.document_type,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Template '{payload.name}' already exists for {payload.document_type}",
        )

    columns_with_order = [
        {"name": col.name, "type": col.type, "order": i}
        for i, col in enumerate(payload.columns)
    ]

    tpl = ColumnTemplate(
        user_id=current_user.id,
        client_id=current_user.client_id,      # Tag template with creator's company
        name=payload.name,
        document_type=payload.document_type,
        description=payload.description,
        columns_json=json.dumps(columns_with_order),
        column_order_json=None,
        is_shared=payload.is_shared and current_user.role in ("admin", "company_admin"),
    )
    # Template shape (2a) — computed once at save time, best-effort.
    _compute_and_store_shape(tpl)
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return _to_response(tpl)


@router.put("/{template_id}", response_model=TemplateResponse)
def update_template(
    template_id: int,
    payload: TemplateUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tpl = _get_template_or_403(template_id, current_user, db)

    if payload.name is not None:
        tpl.name = payload.name
    if payload.document_type is not None:
        tpl.document_type = payload.document_type
    description_changed = False
    if payload.description is not None:
        description_changed = payload.description != tpl.description
        tpl.description = payload.description
    if payload.columns is not None:
        columns_with_order = [
            {"name": col.name, "type": col.type, "order": i}
            for i, col in enumerate(payload.columns)
        ]
        tpl.columns_json = json.dumps(columns_with_order)
    if payload.is_shared is not None:
        tpl.is_shared = payload.is_shared and current_user.role in ("admin", "company_admin")

    # Re-derive the shape only when the grid layout changed.
    if description_changed:
        print(f"[TEMPLATE] shape regenerated on template update (id={tpl.id})",
              flush=True)
        _compute_and_store_shape(tpl)

    tpl.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(tpl)
    return _to_response(tpl)


@router.delete("/{template_id}")
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tpl = _get_template_or_403(template_id, current_user, db)
    db.delete(tpl)
    db.commit()
    return {"message": "Template deleted", "id": template_id}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_and_store_shape(tpl: ColumnTemplate) -> None:
    """
    Phase 2a — derive the template's shape once, at save, and persist it.

    The shape comes from one rule: a cell with text is a static label, an empty
    cell is a slot. Extraction then reads the stored shape instead of
    re-deriving structure from cell text on every run.

    Never raises: a template that fails to yield a shape still saves, and
    extraction falls back to inferring the shape at load.
    """
    try:
        raw = json.loads(tpl.description) if tpl.description else None
        if not (isinstance(raw, dict) and "cells" in raw):
            tpl.set_shape(None)      # not a grid template
            return
    except Exception:
        tpl.set_shape(None)
        return

    try:
        from app.api.routes.extract import _compute_shape_for_grid
        shape = _compute_shape_for_grid(raw)
        tpl.set_shape(shape)
        from template_shape import describe
        print(f"[TEMPLATE] shape: {describe(shape)}", flush=True)
        mig = (shape or {}).get("migration") or {}
        if mig.get("extract_target_cells_with_text"):
            print(f"[TEMPLATE] migration: "
                  f"{mig['extract_target_cells_with_text']} cell(s) were marked "
                  f"'extract here' AND contain text; under the one rule (text = "
                  f"static label) they are now static labels", flush=True)
    except Exception as e:
        tpl.set_shape(None)
        print(f"[TEMPLATE] shape computation failed ({e}) — will infer at load",
              flush=True)




def _get_template_or_403(template_id: int, current_user: User, db: Session) -> ColumnTemplate:
    tpl = db.query(ColumnTemplate).filter(ColumnTemplate.id == template_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    # Super admin can edit anything
    if current_user.role == "admin" and not current_user.client_id:
        return tpl
    # Owner can edit their own
    if tpl.user_id == current_user.id:
        return tpl
    # Company admin can edit templates within their company
    if current_user.role in ("admin", "company_admin") and tpl.client_id == current_user.client_id:
        return tpl
    raise HTTPException(status_code=403, detail="Not your template")


def _parse_columns(tpl: ColumnTemplate) -> list[TemplateColumn]:
    try:
        raw = json.loads(tpl.columns_json) if tpl.columns_json else []
    except Exception:
        return []

    columns = []
    for i, item in enumerate(raw):
        if isinstance(item, str):
            columns.append(TemplateColumn(name=item, type="Text", order=i))
        elif isinstance(item, dict):
            columns.append(TemplateColumn(
                name=item.get("name", ""),
                type=item.get("type", "Text"),
                order=item.get("order", i),
            ))
    return sorted(columns, key=lambda c: c.order)


def _to_response(t: ColumnTemplate) -> TemplateResponse:
    return TemplateResponse(
        id=t.id,
        name=t.name,
        document_type=t.document_type,
        description=t.description,
        columns=_parse_columns(t),
        is_default=t.is_default,
        is_shared=t.is_shared,
        created_at=t.created_at,
        shape=t.get_shape() if hasattr(t, "get_shape") else None,
    )
