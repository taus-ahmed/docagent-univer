"""Overnight H4 — the model's raw response is diagnostic, not a record.

`document_results.raw_llm_response` is the provider's exact answer, which
repeats SSNs, account numbers and every value of the document. It is kept
for RAW_RESPONSE_RETENTION_DAYS (default 7) and then cleared (set to NULL;
the extraction itself, `extraction_json`, is untouched). 0 = never stored at
all. The purge runs at startup and then daily. Logs: counts only.
"""
from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Optional

INTERVAL_SEC = 24 * 3600


def raw_days() -> int:
    from app.config import settings
    try:
        return max(int(getattr(settings, "RAW_RESPONSE_RETENTION_DAYS", 7)), 0)
    except (TypeError, ValueError):
        return 7


def keep_raw() -> bool:
    """Is a raw response stored at all? (0 days = no.)"""
    return raw_days() > 0


def purge_raw(db, days: Optional[int] = None, now: Optional[datetime] = None) -> int:
    """Clear raw responses older than `days` (0: every one). Returns how many."""
    from app.models.models import DocumentResult
    days = raw_days() if days is None else max(int(days), 0)
    cutoff = (now or datetime.utcnow()) - timedelta(days=days)
    q = db.query(DocumentResult).filter(DocumentResult.raw_llm_response.isnot(None))
    if days > 0:
        q = q.filter(DocumentResult.created_at < cutoff)
    n = q.update({DocumentResult.raw_llm_response: None}, synchronize_session=False)
    db.commit()
    if n:
        print(f"[RAW-RETENTION] cleared {n} raw model response(s) older than "
              f"{days} day(s)", flush=True)
    return n


def _loop(stop: threading.Event):
    from app.models import SessionLocal
    while True:
        db = SessionLocal()
        try:
            purge_raw(db)
        except Exception as e:                    # the next day tries again
            print(f"[RAW-RETENTION] run failed: {type(e).__name__}", flush=True)
        finally:
            db.close()
        if stop.wait(INTERVAL_SEC):
            return


def start_raw_purge() -> threading.Event:
    """Purge now (in the thread's first pass) and daily; returns the stop event."""
    stop = threading.Event()
    threading.Thread(target=_loop, args=(stop,), name="raw-response-purge",
                     daemon=True).start()
    return stop
