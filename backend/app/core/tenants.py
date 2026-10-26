"""
A firm (tenant) and its first administrator — created in one place.

There is no tenant table: a firm IS its `client_id`, which every data row
carries, plus its YAML schema (`client_schemas`), without which nothing can be
uploaded. Creating a firm therefore means: a schema row (and its copy in
storage) and one administrator, whose password is ONE-TIME (`auth.hash_password
(..., one_time=True)`): it signs in, and every route but changing the password
answers 403 until it is changed.

Used by `scripts/create_tenant.py` and `POST /api/admin/tenants`; both hand the
one-time password back exactly once and never log it.
"""
from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

DEFAULT_SCHEMA = Path(__file__).resolve().parents[2] / "engine" / "demo_accounting.yaml"


class TenantError(ValueError):
    """The firm cannot be created as asked; the message says why."""


def one_time_password() -> str:
    """24 URL-safe characters (~143 bits) — read out once, then replaced."""
    return secrets.token_urlsafe(18)


def schema_for(client_id: str, client_name: str, template: str | None = None) -> str:
    """The firm's YAML: the template (default: the demo accounting schema) with
    its own client_id and client_name."""
    import yaml
    text = template if template is not None else DEFAULT_SCHEMA.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict) or not isinstance(data.get("document_types"), dict):
        raise TenantError("the schema template has no document_types")
    data["client_id"] = client_id
    data["client_name"] = client_name
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True)


def create_tenant(db, client_id: str, client_name: str, admin_username: str,
                  admin_display_name: str | None = None, schema_yaml: str | None = None,
                  created_by: int | None = None, storage=None) -> dict:
    """Create the firm and its first admin. Returns {client_id, admin_username,
    admin_id, one_time_password}. Refuses (TenantError) an invalid id, an id
    that already has a schema or users, or a username already taken."""
    from app.core.auth import hash_password
    from app.core.storage import get_storage
    from app.models.models import ClientSchema, User
    from app.schemas.schemas import CLIENT_ID_PATTERN

    client_id = (client_id or "").strip()
    client_name = (client_name or "").strip()
    admin_username = (admin_username or "").strip()
    if not re.match(CLIENT_ID_PATTERN, client_id):
        raise TenantError("firm id may use letters, digits, '.', '_' and '-' only "
                          "(and must start and end with a letter or digit)")
    if not client_name:
        raise TenantError("firm name is required")
    if not (3 <= len(admin_username) <= 50):
        raise TenantError("admin username must be 3 to 50 characters")
    if db.query(ClientSchema).filter(ClientSchema.client_id == client_id).first() \
            or db.query(User).filter(User.client_id == client_id).first():
        raise TenantError(f"firm {client_id!r} already exists")
    if db.query(User).filter(User.username == admin_username).first():
        raise TenantError(f"username {admin_username!r} is taken")

    text = schema_for(client_id, client_name, schema_yaml)
    import yaml
    doc_types = list((yaml.safe_load(text) or {}).get("document_types", {}).keys())
    password = one_time_password()
    (storage or get_storage()).save_schema(text, client_id)
    db.add(ClientSchema(client_id=client_id, client_name=client_name,
                        yaml_content=text, document_types=json.dumps(doc_types),
                        created_by=created_by))
    admin = User(username=admin_username,
                 display_name=(admin_display_name or admin_username).strip(),
                 password_hash=hash_password(password, one_time=True),
                 role="admin", client_id=client_id, is_active=True)
    db.add(admin)
    db.commit()
    db.refresh(admin)
    print(f"[TENANT] firm created with admin user {admin.id}", flush=True)  # ids only
    return {"client_id": client_id, "admin_username": admin_username,
            "admin_id": admin.id, "one_time_password": password}


def set_tenant_active(db, client_id: str, active: bool) -> int:
    """Deactivate (or reactivate) every user of a firm. Returns how many
    changed. Data is untouched; a deactivated user cannot sign in and every
    token they hold stops working (`get_current_user` checks is_active)."""
    from app.models.models import User
    n = 0
    for u in db.query(User).filter(User.client_id == client_id).all():
        if u.is_active != active:
            u.is_active = active
            n += 1
    db.commit()
    print(f"[TENANT] {n} users {'re' if active else 'de'}activated", flush=True)
    return n
