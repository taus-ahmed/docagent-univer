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
            from app.config import settings
            doc = P.read_document(path, ocr=bool(getattr(settings,
                                                         "STRUCTURE_OCR_AT_EXTRACTION", False)))
        except Exception as e:
            print(f"[PERCEPTION] {doc_ref(key)}: not stored ({exc_brief(e)})", flush=True)
    cache[key] = doc
    return doc


def packed_for(path, extracted: dict, cache: dict, orchestrator=None):
    """The packed perception of the pages this record covers (with model
    layout plans when STRUCTURE_PLANS_AT_EXTRACTION is on and an
    orchestrator is given)."""
    import perception as P
    doc = read(path, cache)
    if not doc:
        return None
    if orchestrator is not None and not doc.get("plans"):
        from app.config import settings
        if getattr(settings, "STRUCTURE_PLANS_AT_EXTRACTION", False):
            att = plan_pages(doc, orchestrator, path)
            if att and isinstance(extracted, dict):
                # what the plans cost is the document's cost (Run T1, 1b)
                extracted.setdefault("diagnostics", {})["structure_attempts"] = att
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


def plan_pages(perc, orchestrator, file_path, model=None, log=print):
    """Run T1, 3b/3g: model layout plans for every page of `perc`, stored on
    it (`perc["plans"]`), cached by file hash + model + prompt version. Only
    when STRUCTURE_PLANS_AT_EXTRACTION is on; never fatal - a page whose
    plan cannot be had is laid out from geometry at export time."""
    import llm_contract as C
    import structure_engine as S
    from extractor import _llm_json
    model = model or C.setting("GEMINI_MODEL", "") or ""
    images = _page_images(file_path)

    def ask_page(page):
        img = images.get(page["page"])

        def ask(prompt, line_ids):
            from app.config import settings
            budget = int(getattr(settings, "GEMINI_THINKING_BUDGET_PLAN", 0))
            with C.section(f"structure plan p{page['page']}"):
                return _llm_json(orchestrator, prompt, S.SYSTEM,
                                 images=[img] if img else None,
                                 text="" if img else prompt, temperature=0.0,
                                 thinking_budget=budget)
        return ask
    with C.collect_attempts(fresh=True) as attempts:
        try:
            S.make_plans(perc, ask_page, S.file_hash(file_path), model,
                         log=lambda s: log(f"[STRUCTURE] {s}"))
        except Exception as e:
            log(f"[STRUCTURE] plans not made ({exc_brief(e)}); geometry will be used")
    return list(attempts)


def _page_images(file_path) -> dict:
    """page number -> base64 JPEG, or {} when pages cannot be rendered."""
    try:
        from pdf2image import convert_from_path
        import base64
        import io
        out = {}
        for i, im in enumerate(convert_from_path(str(file_path), dpi=110), 1):
            buf = io.BytesIO()
            im.convert("RGB").save(buf, "JPEG", quality=80)
            out[i] = base64.b64encode(buf.getvalue()).decode("ascii")
        return out
    except Exception:
        return {}
