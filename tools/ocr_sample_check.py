"""Run T2, Stage 4: scanned samples through OCR -> perception -> structure
layout, against the digital original each scan was made from.

    backend\\.venv\\Scripts\\python.exe tools\\ocr_sample_check.py [scan_name ...]

`local_docs/DocAgent_testdocs/scans_made/scan_X.pdf` is a printed-and-
scanned copy of `X.pdf` elsewhere in the corpus, so the original's TEXT
LAYER is what the scan should read as. Per sample:

  words expected   the original's text-layer words (whitespace tokens)
  words found      the scan's OCR words
  recall           expected words found (multiset, case kept, punctuation kept)
  precision        found words that are expected
  trust            the perception's per-page OCR trust (character-weighted
                   Tesseract confidence)
  cells kept       the original's structure-layout cell texts that the scan's
                   layout also has, as cells
Prints the reader and whether it is the pinned release: numbers from a
reader other than the pin are NOT production numbers.
"""
from __future__ import annotations

import io
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT / "backend" / "engine", ROOT / "backend", ROOT):
    sys.path.insert(0, str(p))
DOCS = ROOT / "local_docs" / "DocAgent_testdocs"
DEFAULT = ["scan_ccsu_invoice", "scan_utep_paystub", "scan_irs_w2_2021"]


def _original(scan_name):
    want = scan_name.replace("scan_", "", 1) + ".pdf"
    hits = [p for p in DOCS.rglob(want) if "scans_made" not in p.parts]
    return hits[0] if hits else None


def check(scan_name) -> dict:
    import perception as P
    import structure_engine as S
    scan = DOCS / "scans_made" / f"{scan_name}.pdf"
    orig = _original(scan_name)
    sd = P.read_document(scan, ocr=True)
    od = P.read_document(orig)
    exp = Counter(w["text"] for p in od["pages"] for w in p["words"] if w["origin"] == "text")
    got = Counter(w["text"] for p in sd["pages"] for w in p["words"] if w["origin"] == "ocr")
    hit = sum((exp & got).values())
    s_lay, o_lay = S.layout_document(sd), S.layout_document(od)
    s_cells = Counter(c["text"] for cs in s_lay["pages"] for c in cs)
    o_cells = Counter(c["text"] for cs in o_lay["pages"] for c in cs)
    kept = sum((o_cells & s_cells).values())
    recs = [p.get("ocr") or {} for p in sd["pages"]]
    return {"scan": scan_name, "original": str(orig.relative_to(DOCS)) if orig else None,
            "pages": len(sd["pages"]),
            "pages_ocr": sum(1 for r in recs if r.get("reader")),
            "words_expected": sum(exp.values()), "words_found": sum(got.values()),
            "recall": round(hit / max(1, sum(exp.values())), 3),
            "precision": round(hit / max(1, sum(got.values())), 3),
            "trust": [r.get("trust") for r in recs],
            "cells_original": sum(o_cells.values()), "cells_kept": kept,
            "skipped": s_lay["skipped"], "flags": s_lay["flags"][:4],
            "missing_examples": list((exp - got).keys())[:12]}


def main():
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    import ocr_source as O
    print(O.log_line())
    names = sys.argv[1:] or DEFAULT
    out = [check(n) for n in names]
    for r in out:
        print(f"{r['scan']:22s} pages {r['pages_ocr']}/{r['pages']} OCR  words found "
              f"{r['words_found']} vs expected {r['words_expected']}  recall {r['recall']:.1%}  "
              f"precision {r['precision']:.1%}  trust {r['trust']}  cells kept "
              f"{r['cells_kept']}/{r['cells_original']}")
        print(f"   missing e.g.: {r['missing_examples']}")
        if r["skipped"]:
            print(f"   skipped: {r['skipped']}")
    dest = ROOT / "local_docs" / "corpus_metrics" / "t2_ocr_samples.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps({"reader": O.log_line(), "samples": out}, indent=1),
                    encoding="utf-8")


if __name__ == "__main__":
    main()
