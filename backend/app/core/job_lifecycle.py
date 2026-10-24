"""
A job's end of life: hard delete, cancel, and recovery after a restart.

None of this needs a migration. The job row keeps its status column values
(pending / processing / completed / partial / failed / cancelled); WHY the
system ended a job, and that its content was deleted, are marks in the job's
existing `notes` column (`ExtractionJob.marks()`).

Log lines name a job by id and say how many things changed — never a file
name, a value or a tenant (docs/SECURITY.md, "Logging").
"""
from __future__ import annotations

import logging
from datetime import datetime

log = logging.getLogger("docagent.jobs")

RUNNING = ("pending", "processing")


class PurgeIncomplete(Exception):
    """Some stored files survived the delete; nothing was marked deleted."""


def _is_storage_key(ref) -> bool:
    return bool(ref) and not str(ref).startswith(("/", "\\")) and ":" not in str(ref)


def purge_job(db, job, user, storage=None) -> dict:
    """Delete a job's content and keep its record.

    Gone: every stored object under the job's prefix (sources, outputs), any
    source key a result names elsewhere under the SAME tenant's prefix, the
    review screen's cached readings of those sources (page and OCR images in
    memory, and their temp copies), and every result row. Kept: the job row's
    id, owner, tenant, timestamps and counts, with a `deleted` mark
    {at, by, files, results}. The caller has checked permission and that the
    job is not running.

    Idempotent: a second call deletes whatever is still there (normally
    nothing) and keeps the first mark. Files are deleted and VERIFIED gone
    before any row is touched; if any survive, PurgeIncomplete is raised and
    the job is left unmarked, so a retry finishes the work.
    """
    from app.core.storage import get_storage
    from app.models.models import DocumentResult
    storage = storage or get_storage()

    first = job.marks().get("deleted")
    docs = db.query(DocumentResult).filter(DocumentResult.job_id == job.id).all()

    prefix = storage.job_prefix(job.client_id, job.id)
    tenant_prefix = prefix.rsplit("/jobs/", 1)[0] + "/"
    keys, outside = set(), set()
    for d in docs:
        keys.add(storage.upload_key(job.client_id, job.id,
                                    d.original_filename or d.filename))
        if d.s3_key:
            keys.add(d.s3_key)
            if (_is_storage_key(d.s3_key) and d.s3_key.startswith(tenant_prefix)
                    and not d.s3_key.startswith(prefix + "/")):
                outside.add(d.s3_key)

    from app.api.routes.review import forget_sources
    readings = forget_sources(keys)

    files = storage.delete_prefix(prefix)
    for k in sorted(outside):
        if storage.exists(k) and storage.delete(k):
            files += 1
    left = storage.count_prefix(prefix) + sum(1 for k in outside if storage.exists(k))
    if left:
        log.warning("job %s: delete incomplete, %d stored files remain", job.id, left)
        raise PurgeIncomplete(left)

    results = len(docs)
    for d in docs:
        db.delete(d)
    job.output_file = None
    job.output_s3_key = None
    job.input_folder = None
    job.error_message = None
    job.progress_message = None
    mark = first if isinstance(first, dict) else {
        "at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "by": getattr(user, "id", None), "files": files, "results": results}
    job.set_mark("deleted", mark)
    db.commit()
    # ids and counts only
    print(f"[DELETE] job {job.id}: {files} files, {results} results, "
          f"{readings} cached readings removed"
          f"{' (repeat)' if first else ''}", flush=True)
    return {"job_id": job.id, "deleted_at": mark["at"],
            "already_deleted": bool(first), "files_deleted": files,
            "results_deleted": results}
