"""Retry the image-based documents through the OCR word-box path (Run S, 4e).

    backend\\.venv\\Scripts\\python.exe tools\\retry_image_docs.py

For each stored job of an image-based document - the pay stubs printed as
pictures (ou_check_stub: a picture on a page with a native text layer;
saltlake_paycheck: a scanned page 2) and the receipt photos - every value of
the stored model answer is looked for in the OCR reader's words, read two
ways:

  before   OcrPageSource(cleanup="none")   (the reader as it was)
  after    OcrPageSource()                  (Stage 4: `auto` cleanup)

A value is READ when its words appear, in order and contiguous, on one line
of the reading (tools/eval_synthetic_checks.field_read) - the precondition
for grounding it. Image files are read whole; a PDF page is read whole when
it has no text layer, and its pictures are read (cropped) when it does.
No model is called. Writes local_docs/corpus_metrics/retry_image_docs.json.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JOBS = [60, 121, 66, 71, 122, 123, 124]


def _answer_values(doc):
    try:
        ans = json.loads(doc.get("raw_llm_response") or "")
    except (TypeError, ValueError):
        return []
    out = []
    for v in (ans.get("fields") or {}).values():
        out.append(v.get("value") if isinstance(v, dict) else v)
    for rows in (ans.get("tables") or {}).values():
        for r in rows or ():
            if isinstance(r, dict):
                cells = r.get("cells") if isinstance(r.get("cells"), dict) else r
                out += [x for k, x in cells.items() if k not in ("source", "page", "cells")]
    return [str(v) for v in out if v is not None and str(v).strip()]


def _images(path: Path):
    from PIL import Image
    if path.suffix.lower() != ".pdf":
        return [Image.open(path).convert("RGB")]
    import pdfplumber
    import external_tools
    out = []
    with pdfplumber.open(str(path)) as pdf:
        for n, page in enumerate(pdf.pages, 1):
            img = external_tools.render(path, dpi=300, first_page=n, last_page=n)[0]
            words = page.extract_words()
            if len(words) < 5:
                out.append(img.convert("RGB"))
                continue
            sx, sy = img.width / float(page.width), img.height / float(page.height)
            for im in page.images or []:
                box = (int(im["x0"] * sx), int(im["top"] * sy),
                       int(im["x1"] * sx), int(im["bottom"] * sy))
                if (box[2] - box[0]) * (box[3] - box[1]) > 0.05 * img.width * img.height:
                    out.append(img.crop(box).convert("RGB"))
    return out


def main() -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    import replay_raw
    import eval_synthetic_checks as E
    replay_raw._setup()
    from ocr_source import OcrPageSource
    rows = []
    for jid in JOBS:
        if not replay_raw.has_raw(jid):
            continue
        for doc in replay_raw.load_job(jid)["docs"]:
            name = doc.get("original_filename") or ""
            src = replay_raw.find_source(name)
            vals = _answer_values(doc)
            if not src or not vals:
                continue
            imgs = _images(src)
            got = {}
            for tag, kw in (("before", {"cleanup": "none"}), ("after", {})):
                lines = []
                for im in imgs:
                    s = OcrPageSource(im, dpi=300, **kw)
                    lines += E.lines_of(s.words())
                got[tag] = sum(1 for v in vals if E.field_read(v, lines))
            rows.append({"job": jid, "file": name, "values": len(vals),
                         "read_before": got["before"], "read_after": got["after"],
                         "images": len(imgs)})
            print(f"job {jid:<4} {name[:32]:<32} values {len(vals):>3}  read by OCR "
                  f"{got['before']:>3} -> {got['after']:>3}  ({len(imgs)} image(s))", flush=True)
    out = ROOT / "local_docs" / "corpus_metrics" / "retry_image_docs.json"
    out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
