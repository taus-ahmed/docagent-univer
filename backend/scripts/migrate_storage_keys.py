"""
Phase 8 storage migration — report and backfill.

WHAT IS AND IS NOT RECOVERABLE
------------------------------
Nothing here restores a lost file, because the files were never anywhere else.
Before Phase 8 an upload was written to `./storage/uploads/{job_id}/{name}` on
the web container's own disk, `DocumentResult.s3_key` was never populated, and
`save_output` was never called at all. On Railway with no volume that disk is
new at every deploy.

So, for every existing document result:

  extracted values   INTACT. `extraction_json` holds everything the export
                     needs, and exports are BUILT ON DEMAND from it — they were
                     never files, so there is nothing to lose and nothing to
                     migrate.
  raw LLM response   INTACT, in `raw_llm_response`.
  the source PDF     GONE for any job older than the current container, and
                     UNRECOVERABLE — no second copy was ever written. This
                     script does not pretend otherwise; it records the absence
                     so the UI can say "source not retained" instead of
                     offering a download that 404s.

`s3_key` is therefore left NULL for historical rows, and NULL now means exactly
one thing: no source document is retained for this result. New rows written
after Phase 8 carry a real key.

Run:  python -m scripts.migrate_storage_keys            # report only
      python -m scripts.migrate_storage_keys --apply    # adopt files still on disk
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.storage import get_storage          # noqa: E402
from app.models import SessionLocal               # noqa: E402
from app.models.models import DocumentResult, ExtractionJob  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="adopt any source file still present on local disk "
                         "into the new key layout, and record its key")
    args = ap.parse_args()

    db = SessionLocal()
    storage = get_storage()
    try:
        results = db.query(DocumentResult).order_by(DocumentResult.id).all()
        jobs = {j.id: j for j in db.query(ExtractionJob).all()}

        have_values = sum(1 for r in results if (r.extraction_json or "").strip())
        have_raw = sum(1 for r in results if (r.raw_llm_response or "").strip())
        already_keyed = sum(1 for r in results if (r.s3_key or "").strip())

        adopted, still_on_disk = 0, 0
        legacy_root = Path(getattr(__import__("app.config", fromlist=["settings"]).settings,
                                   "LOCAL_UPLOAD_DIR"))

        for r in results:
            if (r.s3_key or "").strip():
                continue
            legacy = legacy_root / str(r.job_id) / r.filename
            if not legacy.exists():
                continue
            still_on_disk += 1
            if not args.apply:
                continue
            job = jobs.get(r.job_id)
            client_id = getattr(job, "client_id", None) or "anon"
            try:
                key, _ = storage.save_upload(legacy.read_bytes(), r.filename,
                                             r.job_id, client_id=client_id)
                r.s3_key = key
                adopted += 1
            except Exception as e:
                print(f"  ! {r.id} {r.filename}: {e}")
        if args.apply and adopted:
            db.commit()

        n = len(results)
        print(f"document results            : {n}")
        print(f"  extracted values retained : {have_values}"
              f"{'  (ALL)' if have_values == n else ''}")
        print(f"  raw LLM response retained : {have_raw}")
        print(f"  already carrying a key    : {already_keyed}")
        print(f"  source still on this disk : {still_on_disk}")
        if args.apply:
            print(f"  adopted into the new layout: {adopted}")
        else:
            print(f"  (re-run with --apply to adopt those {still_on_disk})")
        lost = n - already_keyed - still_on_disk
        print(f"  source unrecoverable      : {lost}   "
              f"(never copied anywhere; s3_key stays NULL, which means "
              f"'no source retained')")
        print()
        print("Exports are rebuilt from extraction_json on every download, so "
              "no export file needed migrating.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
