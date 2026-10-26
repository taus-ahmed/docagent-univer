"""Create a firm and its first administrator — non-interactive.

    python scripts/create_tenant.py --firm-id smith_cpa --firm-name "Smith CPA" \\
        --admin-username smith_admin --confirm-database remote

Reads the database from DATABASE_URL (the same variable the app reads) and
never prints it: `--confirm-database` must name the database's host class,
`local` (SQLite, localhost, the compose service) or `remote` (anything else),
or nothing is done. Prints the admin's ONE-TIME password once, to this
terminal only; it is never logged or written anywhere. The admin must change it
at first sign-in (every other action answers 403 until then).

Optional: --admin-display-name, --schema path/to/firm.yaml (default: the demo
accounting schema, renamed to this firm). Exit 0 on success, 2 when refused.
See docs/ONBOARDING-A-CLIENT.md.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres", ""}


def host_class(url: str) -> str:
    """"local" or "remote" — the only thing ever said about the URL."""
    from urllib.parse import urlsplit
    if url.startswith("sqlite"):
        return "local"
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return "remote"
    return "local" if host in LOCAL_HOSTS else "remote"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="create a firm and its first admin")
    ap.add_argument("--firm-id", required=True)
    ap.add_argument("--firm-name", required=True)
    ap.add_argument("--admin-username", required=True)
    ap.add_argument("--admin-display-name")
    ap.add_argument("--schema", help="YAML schema for the firm (default: demo schema)")
    ap.add_argument("--confirm-database", choices=("local", "remote"), required=True,
                    help="the database's host class; must match or nothing is done")
    a = ap.parse_args(argv)

    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("refused: DATABASE_URL is not set", file=sys.stderr)
        return 2
    cls = host_class(url)
    if a.confirm_database != cls:
        print(f"refused: this database is {cls}; pass --confirm-database {cls} "
              "if that is the one you mean", file=sys.stderr)
        return 2

    for p in (ROOT / "backend", ROOT / "backend" / "engine"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))
    from app.core.tenants import TenantError, create_tenant
    from app.models import SessionLocal
    from app.models.models import Base

    schema = Path(a.schema).read_text(encoding="utf-8") if a.schema else None
    db = SessionLocal()
    try:
        if cls == "local":                        # a fresh local database: the tables
            Base.metadata.create_all(db.get_bind())
        out = create_tenant(db, a.firm_id, a.firm_name, a.admin_username,
                            a.admin_display_name, schema)
    except TenantError as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2
    finally:
        db.close()
    print(f"firm {out['client_id']} created; admin {out['admin_username']} (user {out['admin_id']})")
    print("ONE-TIME PASSWORD (shown once, not stored anywhere readable):")
    print(f"    {out['one_time_password']}")
    print("Give it to the admin by a different channel than the username; they "
          "must change it at first sign-in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
