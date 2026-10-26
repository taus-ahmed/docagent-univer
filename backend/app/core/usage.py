"""
Pages per firm per calendar month — the cost control (no migration).

    TENANT_MONTHLY_PAGE_LIMIT   0 (default) = unlimited; a positive number
                                caps every firm's pages per calendar month (UTC)
    monthly_page_limit: N       optional, in a firm's own YAML schema
                                (`client_schemas.yaml_content`): overrides the
                                global value for that firm; 0 = unlimited

What counts: the pages a job was STARTED with, recorded on the job as the
`pages` mark (`ExtractionJob.notes`) when it is created — a PDF's page count,
1 for an image. A job is counted whatever became of it (failed, cancelled,
hard-deleted: the mark survives a delete), because the model was asked for it.
A job created before this mark existed counts one page per document; that
undercounts multi-page PDFs from before round 14 and only for the month in
which they ran.

A job that would take a firm over its limit is refused before anything is
stored or started (`check_page_quota`, HTTP 429). Two uploads checked in the
same instant on different processes could both pass; one process (today's
deployment) serialises them, because the check and the job's creation happen
with no await between them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import HTTPException

PAGES_MARK = "pages"


def month_start(now: Optional[datetime] = None) -> datetime:
    now = now or datetime.utcnow()
    return datetime(now.year, now.month, 1)


def next_month_start(now: Optional[datetime] = None) -> datetime:
    s = month_start(now)
    return datetime(s.year + (s.month == 12), s.month % 12 + 1, 1)


def job_pages(job) -> int:
    """Pages the job was started with (the mark), else one per document."""
    p = job.marks().get(PAGES_MARK)
    if isinstance(p, int) and not isinstance(p, bool) and p >= 0:
        return p
    return int(job.total_docs or 0)


def pages_used(db, client_id: str, now: Optional[datetime] = None) -> int:
    from app.models.models import ExtractionJob
    start, end = month_start(now), next_month_start(now)
    jobs = (db.query(ExtractionJob)
              .filter(ExtractionJob.client_id == client_id,
                      ExtractionJob.created_at >= start,
                      ExtractionJob.created_at < end).all())
    return sum(job_pages(j) for j in jobs)


def _firm_override(db, client_id: str) -> Optional[int]:
    """`monthly_page_limit` from the firm's YAML schema, or None."""
    import yaml
    from app.models.models import ClientSchema
    row = db.query(ClientSchema).filter(ClientSchema.client_id == client_id).first()
    if row is None:
        return None
    try:
        v = (yaml.safe_load(row.yaml_content or "") or {}).get("monthly_page_limit")
    except Exception:
        return None
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        return None
    return v


def page_limit(db, client_id: str) -> tuple[int, str]:
    """(limit, source): 0 means unlimited; source is "firm" or "global"."""
    from app.config import settings
    firm = _firm_override(db, client_id)
    if firm is not None:
        return firm, "firm"
    g = int(getattr(settings, "TENANT_MONTHLY_PAGE_LIMIT", 0) or 0)
    return max(g, 0), "global"


def usage(db, client_id: str, now: Optional[datetime] = None) -> dict:
    limit, source = page_limit(db, client_id)
    used = pages_used(db, client_id, now)
    return {"client_id": client_id,
            "month": month_start(now).strftime("%Y-%m"),
            "pages_used": used, "page_limit": limit, "limit_source": source,
            "pages_remaining": None if limit == 0 else max(limit - used, 0),
            "resets_on": next_month_start(now).date().isoformat()}


def check_page_quota(db, client_id: str, pages: int,
                     now: Optional[datetime] = None) -> None:
    """Refuse (429) a job that would take the firm past its monthly limit."""
    u = usage(db, client_id, now)
    limit = u["page_limit"]
    if limit == 0 or u["pages_used"] + pages <= limit:
        return
    # ids and counts only
    print(f"[QUOTA] refused: {pages} pages, {u['pages_used']}/{limit} used "
          f"this month", flush=True)
    raise HTTPException(
        status_code=429,
        detail=(f"Monthly page limit reached: this upload has {pages} page(s) and "
                f"your firm has used {u['pages_used']} of its {limit} pages for "
                f"{u['month']}. Nothing was processed. The limit resets on "
                f"{u['resets_on']}; your administrator can see the usage."))
