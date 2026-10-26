"""
Opt-in retention: delete jobs older than DATA_RETENTION_DAYS, firm by firm.

    DATA_RETENTION_DAYS   0 (default) = off; nothing is ever purged and the
                          daily task is not started

A job is due when it finished (`completed_at`, else `created_at`) more than
the period ago, is not running, and is not already deleted. Each due job goes
through `job_lifecycle.purge_job` — the same function as the hard-delete
route: files first, verified gone, then rows; the job record stays, marked
deleted by "retention". Firms are handled one at a time, and every query names
the firm, so a purge of one firm cannot reach another's jobs. A job whose
files will not delete is left unmarked and retried the next day.

Logs: job ids and counts only. One period for every firm; per-firm periods and
an audit table need a migration (docs/proposals/retention-v2.md).
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Optional

#: purge_job records who deleted; the purge is nobody's account
RETENTION_ACTOR = SimpleNamespace(id="retention")
FIRST_RUN_DELAY_SEC = 600
INTERVAL_SEC = 24 * 3600


def retention_days() -> int:
    from app.config import settings
    try:
        return max(int(getattr(settings, "DATA_RETENTION_DAYS", 0) or 0), 0)
    except (TypeError, ValueError):
        return 0


def due_jobs(db, client_id: str, days: int, now: Optional[datetime] = None):
    from sqlalchemy import func
    from app.core.job_lifecycle import RUNNING
    from app.models.models import ExtractionJob
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    q = (db.query(ExtractionJob)
           .filter(ExtractionJob.client_id == client_id,
                   ExtractionJob.status.notin_(RUNNING),
                   func.coalesce(ExtractionJob.completed_at,
                                 ExtractionJob.created_at) < cutoff)
           .order_by(ExtractionJob.id))
    return [j for j in q.all() if not j.marks().get("deleted")]


def purge_firm(db, client_id: str, days: int, now: Optional[datetime] = None) -> dict:
    """Purge one firm's due jobs. {purged: [ids], failed: [ids]}."""
    from app.core.job_lifecycle import PurgeIncomplete, purge_job
    out = {"purged": [], "failed": []}
    if days <= 0:
        return out
    for job in due_jobs(db, client_id, days, now):
        if job.client_id != client_id:          # belt and braces: never another firm's
            continue
        try:
            purge_job(db, job, RETENTION_ACTOR)
            out["purged"].append(job.id)
        except PurgeIncomplete:
            db.rollback()
            out["failed"].append(job.id)
    return out


def purge_expired(db, days: Optional[int] = None, now: Optional[datetime] = None) -> dict:
    """Every firm, one at a time. Returns {firms, purged, failed} counts."""
    from app.models.models import ExtractionJob
    days = retention_days() if days is None else days
    totals = {"firms": 0, "purged": 0, "failed": 0}
    if days <= 0:
        return totals
    firms = sorted(c for (c,) in db.query(ExtractionJob.client_id).distinct() if c)
    for cid in firms:
        r = purge_firm(db, cid, days, now)
        if r["purged"] or r["failed"]:
            totals["firms"] += 1
            # ids and counts only — the job ids, never the firm id
            print(f"[RETENTION] {len(r['purged'])} jobs purged {r['purged']}"
                  + (f", {len(r['failed'])} to retry {r['failed']}" if r["failed"] else ""),
                  flush=True)
        totals["purged"] += len(r["purged"])
        totals["failed"] += len(r["failed"])
    print(f"[RETENTION] run done: {totals['purged']} purged, {totals['failed']} "
          f"to retry, older than {days} days", flush=True)
    return totals


def _loop(stop: threading.Event):
    from app.models import SessionLocal
    if stop.wait(FIRST_RUN_DELAY_SEC):
        return
    while True:
        days = retention_days()
        if days > 0:
            db = SessionLocal()
            try:
                purge_expired(db, days)
            except Exception as e:                 # the next day tries again
                print(f"[RETENTION] run failed: {type(e).__name__}", flush=True)
            finally:
                db.close()
        if stop.wait(INTERVAL_SEC):
            return


def start_daily_purge() -> Optional[threading.Event]:
    """Start the daily purge thread when DATA_RETENTION_DAYS > 0; returns its
    stop event, or None (and starts nothing) when retention is off. One
    process: like `_release_stranded_jobs`, this assumes a single instance."""
    days = retention_days()
    if days <= 0:
        return None
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), name="retention-purge",
                     daemon=True).start()
    print(f"[RETENTION] daily purge on: jobs older than {days} days", flush=True)
    return stop
