"""What a demo account has been doing. READ-ONLY.

    backend\\.venv\\Scripts\\python.exe -m scripts.demo_activity_report pearx_demo
    ... pearx_demo --limit 200
    ... pearx_demo --event upload --event export
    ... pearx_demo --utc

Prints `demo_activity` for one client_id, NEWEST FIRST, with the status of the
job each row refers to.

TIMES ARE AMERICA/PHOENIX. The rows are stored in naive UTC, like every other
timestamp in this project (`DemoActivity.ts`, `ExtractionJob.created_at`), and
converted here for reading. Phoenix does not observe DST, so the offset is a
constant -07:00 and a machine with no tz database still prints the right wall
clock (there is a fallback for exactly that). `--utc` prints the stored values
instead, which is what to use when comparing against a log line.

It issues SELECTs and nothing else: no INSERT, no UPDATE, no DELETE, no DDL. It
does not create the table either — if `demo_activity` does not exist yet, it
says so and stops, because a report that silently creates an empty table would
read as "nothing happened".
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
for _p in (str(_BACKEND), str(_BACKEND.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PHOENIX_FALLBACK = timezone(timedelta(hours=-7), "MST")


def _phoenix():
    """America/Phoenix, or a fixed -07:00 if no tz database is installed.

    The fallback is exact rather than approximate: Arizona has not observed DST
    since 1968, so UTC-7 IS Phoenix all year. It is a fallback only because
    `zoneinfo` raises on a Windows box without the `tzdata` package.
    """
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("America/Phoenix")
    except Exception:
        return PHOENIX_FALLBACK


def _fmt_ts(ts, tz) -> str:
    if ts is None:
        return "(no timestamp)"
    if tz is None:
        return ts.strftime("%Y-%m-%d %H:%M:%S") + " UTC"
    # Stored naive UTC -> aware UTC -> the reader's zone.
    return (ts.replace(tzinfo=timezone.utc).astimezone(tz)
              .strftime("%Y-%m-%d %H:%M:%S %Z"))


def _fmt_detail(raw) -> str:
    """`detail` on one line, with the file list collapsed to what it says."""
    if not raw:
        return ""
    try:
        d = json.loads(raw)
    except Exception:
        return str(raw)[:120]
    bits = []
    for f in d.get("files") or []:
        kb = (f.get("size_bytes") or 0) / 1024
        bits.append(f"{f.get('filename')} ({kb:.0f} KB)")
    if d.get("filename") and not bits:
        bits.append(str(d["filename"]))
    for key in ("template", "reason", "kind", "username", "ip", "status"):
        if d.get(key) not in (None, "", []):
            bits.append(f"{key}={d[key]}")
    if d.get("options_requested"):
        bits.append(f"options={d['options_requested']}")
    return "; ".join(bits)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("client_id", help="the demo tenant, e.g. pearx_demo")
    ap.add_argument("--limit", type=int, default=100,
                    help="rows to print, newest first (default 100)")
    ap.add_argument("--event", action="append", default=None,
                    help="only these events; repeatable")
    ap.add_argument("--utc", action="store_true",
                    help="print stored UTC instead of Phoenix time")
    args = ap.parse_args(argv)

    from sqlalchemy import inspect

    from app.models.models import DemoActivity, ExtractionJob, SessionLocal, engine

    if not inspect(engine).has_table("demo_activity"):
        print("demo_activity does not exist in this database "
              f"({engine.url.render_as_string(hide_password=True)}).\n"
              "It is created by init_db() on the next boot — see the deploy "
              "note in the report. Nothing was created by this script.")
        return 1

    tz = None if args.utc else _phoenix()
    session = SessionLocal()
    try:
        q = (session.query(DemoActivity)
             .filter(DemoActivity.client_id == args.client_id)
             .order_by(DemoActivity.ts.desc(), DemoActivity.id.desc()))
        if args.event:
            q = q.filter(DemoActivity.event.in_(args.event))
        rows = q.limit(args.limit).all()

        if not rows:
            print(f"No activity recorded for client_id={args.client_id!r}.")
            return 0

        # One query for the jobs these rows mention, rather than one per row.
        job_ids = {r.job_id for r in rows if r.job_id}
        jobs = {}
        if job_ids:
            for j in (session.query(ExtractionJob)
                      .filter(ExtractionJob.id.in_(job_ids)).all()):
                jobs[j.id] = j

        print(f"demo_activity — client_id={args.client_id} — {len(rows)} row(s), "
              f"newest first, times in "
              f"{'UTC' if args.utc else 'America/Phoenix'}")
        print("-" * 118)
        print(f"{'WHEN':<26} {'EVENT':<15} {'JOB':>6} {'JOB STATUS':<12} DETAIL")
        print("-" * 118)
        for r in rows:
            job = jobs.get(r.job_id) if r.job_id else None
            if r.job_id and not job:
                status = "(job gone)"
            elif job:
                status = job.status or ""
                if job.total_docs:
                    status = f"{status} {job.successful}/{job.total_docs}"
            else:
                status = ""
            print(f"{_fmt_ts(r.ts, tz):<26} {r.event:<15} "
                  f"{(r.job_id or ''):>6} {status:<12} {_fmt_detail(r.detail)}")
        print("-" * 118)

        counts = {}
        for r in rows:
            counts[r.event] = counts.get(r.event, 0) + 1
        print("totals: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
        if rows:
            print(f"oldest shown: {_fmt_ts(rows[-1].ts, tz)}   "
                  f"newest: {_fmt_ts(rows[0].ts, tz)}")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
