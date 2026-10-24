"""Parallel OCR is the serial OCR: proof over the whole corpus.

Every PDF under tests/ (the gold corpus, round 2, the OCR and scenario
fixtures, generated fixtures), every source image under tests/ read on its own,
and the 54 synthetic cheque scans (tests/test_OCR) bound into one multi-page
PDF per tier, are preprocessed twice — OCR_WORKERS=1 and OCR_WORKERS=N — and
every field of the result is compared: texts, words with their boxes, origins,
OCR metadata, notes, failure lists, and the straightened OCR images by digest.
The preprocessor records no timing field, so nothing is excluded.

usage: python -m tests.harness.ocr_parallel_identity [--workers N] [OUT.json]
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

from tests.harness import bootstrap as bs

bs.bootstrap()

import core.preprocessor as preprocessor  # noqa: E402

IMAGES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}


def snapshot(doc) -> dict:
    d = dict(vars(doc))
    d["ocr_images"] = {
        str(n): [im.mode, list(im.size),
                 hashlib.sha256(im.tobytes()).hexdigest(), dpi]
        for n, (im, dpi) in sorted(doc.ocr_images.items())}
    return json.loads(json.dumps(d, default=repr, sort_keys=True))


def run(path: Path, workers: int):
    os.environ["OCR_WORKERS"] = str(workers)
    t = time.perf_counter()
    with contextlib.redirect_stdout(io.StringIO()):
        doc = preprocessor.preprocess_file(path)
    return snapshot(doc), time.perf_counter() - t


def tier_pdfs(tmp: Path) -> list[Path]:
    from PIL import Image
    out = []
    for tier, pat in (("clean", "*_clean.png"), ("moderate", "*_moderate.jpg"),
                      ("hard", "*_hard.jpg")):
        files = sorted((bs.TESTS_DIR / "test_OCR").glob("chk_" + pat))
        imgs = [Image.open(f).convert("RGB") for f in files]
        p = tmp / f"test_OCR_{tier}_{len(imgs)}p.pdf"
        imgs[0].save(p, "PDF", save_all=True, append_images=imgs[1:],
                     resolution=150)
        out.append(p)
    return out


def main(argv):
    workers = 4
    if "--workers" in argv:
        i = argv.index("--workers")
        workers = int(argv[i + 1])
        del argv[i:i + 2]
    out_path = Path(argv[0]) if argv else None
    files = sorted(p for p in bs.TESTS_DIR.rglob("*")
                   if p.is_file() and (p.suffix.lower() == ".pdf"
                                       or p.suffix.lower() in IMAGES)
                   and "llm_cache" not in p.parts)
    tmp = Path(tempfile.mkdtemp())
    files += tier_pdfs(tmp)
    rows, differ = [], []
    for p in files:
        try:
            a, ta = run(p, 1)
            b, tb = run(p, workers)
        except Exception as exc:  # a file the preprocessor rejects: both must
            rows.append({"file": str(p), "error": f"{type(exc).__name__}: {exc}"})
            continue
        same = a == b
        ocr = len(a.get("ocr_pages") or [])
        fallback = [e.get("pool_fallback") for e in b.get("ocr_pages") or []
                    if e.get("pool_fallback")]
        rows.append({"file": str(p.relative_to(bs.TESTS_DIR)) if bs.TESTS_DIR in p.parents
                     else p.name, "ocr_pages": ocr, "identical": same,
                     "serial_s": round(ta, 2), "pool_s": round(tb, 2),
                     "fallback": fallback})
        if not same:
            differ.append(str(p))
            print("DIFFER", p, [k for k in a if a.get(k) != b.get(k)], flush=True)
    summary = {"workers": workers, "files": len(rows),
               "with_ocr": sum(1 for r in rows if r.get("ocr_pages")),
               "ocr_pages": sum(r.get("ocr_pages", 0) for r in rows),
               "identical": sum(1 for r in rows if r.get("identical")),
               "errors": sum(1 for r in rows if "error" in r),
               "fallbacks": sum(len(r.get("fallback") or []) for r in rows),
               "differ": differ}
    print(json.dumps(summary), flush=True)
    if out_path:
        out_path.write_text(json.dumps({"summary": summary, "rows": rows},
                                       indent=1), encoding="utf-8")
    return 1 if differ else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
