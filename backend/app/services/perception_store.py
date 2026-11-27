"""Run T1, 2f: a document's perception stored with its result.

Read once per FILE when the job saves it (every record of a split file
gets the pages it covers) and packed into `document_results.perception_json`.
Exports and the structure engine read it back with `stored`; the uploaded
file is not needed again. Never fatal: a perception that cannot be read is
stored as nothing and said once in the log."""
from __future__ import annotations

import app.services.paths  # noqa: F401  (engine on sys.path)
from log_safety import doc_ref, exc_brief


def read(path, cache: dict):
    """The whole file's perception, read once per path (None for a non-PDF
    or an unreadable file)."""
    key = str(path)
    if key in cache:
        return cache[key]
    doc = None
    if key.lower().endswith(".pdf"):
        try:
            import perception as P
            doc = P.read_document(path)
        except Exception as e:
            print(f"[PERCEPTION] {doc_ref(key)}: not stored ({exc_brief(e)})", flush=True)
    cache[key] = doc
    return doc


def packed_for(path, extracted: dict, cache: dict):
    """The packed perception of the pages this record covers."""
    import perception as P
    doc = read(path, cache)
    if not doc:
        return None
    rng = (extracted or {}).get("source_pages")
    pages = doc["pages"]
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        try:
            lo, hi = int(rng[0]), int(rng[1])
            pages = [p for p in pages if lo <= p["page"] <= hi]
        except (TypeError, ValueError):
            pass
    return P.pack({**doc, "pages": pages})


def stored(doc_result):
    """The perception stored on a DocumentResult, or None."""
    import perception as P
    return P.unpack(getattr(doc_result, "perception_json", None))
