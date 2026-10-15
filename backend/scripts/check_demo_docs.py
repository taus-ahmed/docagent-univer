"""Do the shipped demo PDFs actually work in the demo?

The demo refuses a document whose text layer would send it to OCR (B2), so a
sample document with no text layer would be offered in the panel and then
rejected the moment an investor clicked Extract. This answers that question
before the demo rather than during it.

It reads the PDF's own text layer through the SAME predicate the pipeline
routes on (`core.preprocessor.pages_without_text_layer`), renders nothing, runs
no OCR, and CALLS NO MODEL.

    backend\\.venv\\Scripts\\python.exe -m scripts.check_demo_docs
    backend\\.venv\\Scripts\\python.exe -m scripts.check_demo_docs pearx_demo

Exit code is 1 if any file would be refused, so it can gate a deploy.
"""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
for _p in (str(_BACKEND / "engine"), str(_BACKEND), str(_BACKEND.parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

PREVIEW_CHARS = 300


def _preview(path: Path) -> str:
    """The first PREVIEW_CHARS characters of the document's own text."""
    import pdfplumber

    out: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            out.append(page.extract_text() or "")
            if sum(len(x) for x in out) >= PREVIEW_CHARS:
                break
    text = " ".join(" ".join(out).split())
    return text[:PREVIEW_CHARS]


def main(argv: list[str]) -> int:
    from core.preprocessor import pages_without_text_layer

    root = _BACKEND / "demo_docs"
    clients = argv[1:] or ([d.name for d in sorted(root.iterdir()) if d.is_dir()]
                           if root.is_dir() else [])
    if not clients:
        print(f"No demo client folders under {root}")
        return 0

    bad = 0
    for client in clients:
        folder = root / client
        pdfs = sorted(p for p in folder.glob("*.pdf")) if folder.is_dir() else []
        print(f"\n=== {client} — {len(pdfs)} PDF(s) in {folder} ===")
        if not pdfs:
            print("  (nothing to check)")
            continue
        for pdf in pdfs:
            try:
                ocr_pages = pages_without_text_layer(pdf)
            except Exception as exc:                      # unreadable file
                bad += 1
                print(f"\n  [UNREADABLE] {pdf.name}: {exc}")
                continue
            size_kb = pdf.stat().st_size / 1024
            if ocr_pages:
                bad += 1
                print(f"\n  [NO TEXT LAYER] {pdf.name} ({size_kb:.0f} KB) — "
                      f"page(s) {ocr_pages} would route to OCR, so the demo "
                      f"REFUSES this file (422).")
            else:
                print(f"\n  [OK] {pdf.name} ({size_kb:.0f} KB) — every page has "
                      f"a text layer.")
            try:
                print(f"       first {PREVIEW_CHARS} chars: {_preview(pdf)!r}")
            except Exception as exc:
                print(f"       (could not read a preview: {exc})")

    print(f"\n{bad} file(s) the demo would refuse.")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
