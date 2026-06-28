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
    # Gemini-based template understanding — compute once at save time (best-effort).
    _compute_and_store_cbm(tpl)
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

    # Re-run Gemini template understanding only when the grid layout changed.
    if description_changed:
        _compute_and_store_cbm(tpl)

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

def _compute_and_store_cbm(tpl: ColumnTemplate) -> None:
    """
    Run Gemini-based template understanding once and store it on the template's
    cell_binding_map. Best-effort: any failure leaves cell_binding_map unset so
    extraction falls back to the existing compute_binding_map path. Never raises.
    """
    try:
        if not tpl.description:
            tpl.set_cell_binding_map(None)
            return
        raw = json.loads(tpl.description)
        if not (isinstance(raw, dict) and "cells" in raw):
            tpl.set_cell_binding_map(None)   # not a grid template (plain text / columns)
            return
    except Exception:
        tpl.set_cell_binding_map(None)
        return

    try:
        # Lazy import — extract.py pulls in heavy engine modules; avoid import cycles.
        from app.api.routes.extract import _understand_template, compute_binding_map

        # Gate by template_type: STRUCTURAL templates (pure column layouts — balance
        # sheets, P&L, payslips with side-by-side sections) are handled best by the
        # three-layer layout path, which uses the section-aware column_groups. Skip
        # CBM for them so extraction falls through to the layout path. Only LABELED /
        # MIXED templates (KV forms, invoices with embedded tables) get a CBM.
        try:
            ttype = (compute_binding_map({}, raw) or {}).get("_meta", {}).get("template_type")
        except Exception:
            ttype = None
        if ttype == "structural":
            had_cbm = bool(tpl.cell_binding_map)
            tpl.set_cell_binding_map(None)
            if had_cbm:
                # FIX 5 — a structural template that previously had a (wrong) CBM
                # stored gets it cleared on re-save.
                print("[TEMPLATE] structural — cleared incorrect CBM", flush=True)
            else:
                print("[TEMPLATE] structural template — CBM skipped, uses layout extraction",
                      flush=True)
            return

        cbm = _understand_template(raw)
        if cbm:
            tpl.set_cell_binding_map(cbm)
            print(
                f"[TEMPLATE] labeled/mixed — CBM stored: "
                f"{len(cbm.get('extract_cells', {}))} cells, "
                f"{len(cbm.get('tables', []))} tables",
                flush=True,
            )
        else:
            tpl.set_cell_binding_map(None)
            print("[TEMPLATE] binding map not computed — extraction will fall back "
                  "to compute_binding_map", flush=True)
    except Exception as e:
        tpl.set_cell_binding_map(None)
        print(f"[TEMPLATE] understanding failed ({e}) — saved without binding map", flush=True)


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
    )
