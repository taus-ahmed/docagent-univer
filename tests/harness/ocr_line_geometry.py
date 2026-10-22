# -*- coding: utf-8 -*-
"""How often D9 flags a value that OCR READ CORRECTLY — per fixture variant.

MEASUREMENT, NOT A BUILD. Gate 2b (red tests: tests/test_ocr_line_geometry.py).

For every scanned page of every generated variant
(tests/fixtures/make_scan_variants.py), every ground-truth field from the
manifest is asked two questions:

  READ     does D9's own rule (`matches_loosely`) find the value in TESSERACT'S
           OWN LINES — the (block, paragraph, line) grouping `raw_text`
           reports? If not, the OCR misread it and no line grouping can help.
  PASSED   of the values READ, does `matches_loosely` also find it in the
           ENGINE'S lines — the geometry `read_page` hands everything
           downstream? A value READ but not PASSED is a TRUE value D9 flags.

    flagged rate = (READ - PASSED) / READ

The production path is used throughout: `render_pdf_page` at OCR_DPI,
`OcrPageSource` (straightening included), `read_page`. `--skew-min` overrides
`ocr_source.SKEW_MIN` for the threshold sweep; nothing else is changed.

    python -m tests.harness.ocr_line_geometry --label before
    python -m tests.harness.ocr_line_geometry --label sweep3 --skew-min 3

Writes <--out>/ocr_line_geometry_<label>.json (default tests/reports).
⚠ SYNTHETIC fixtures.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from tests.harness import bootstrap as bs

bs.bootstrap()

import ocr_source  # noqa: E402
from text_layer import matches_loosely, read_page  # noqa: E402

GENERATOR = bs.TESTS_DIR / "fixtures" / "make_scan_variants.py"
FIELDS = ("bank", "payee", "check_number", "date", "amount_numeral",
          "amount_words_shown", "routing_number", "account_number", "memo")


def raw_lines(text):
    """Tesseract's own lines as word dicts, so `matches_loosely` can read them."""
    return [[{"text": t} for t in ln.split()] for ln in text.split("\n")
            if ln.strip()]


def generate(out):
    proc = subprocess.run([sys.executable, str(GENERATOR), "--out", str(out),
                           "--repo", str(bs.REPO_DIR)], capture_output=True)
    if proc.returncode:
        raise SystemExit(proc.stdout.decode("utf-8", "replace")
                         + proc.stderr.decode("utf-8", "replace"))
    return json.loads((out / "manifest.json").read_text(encoding="utf-8"))


def measure_page(pdf, page):
    image = ocr_source.render_pdf_page(pdf, page, dpi=ocr_source.OCR_DPI)
    src = ocr_source.OcrPageSource(image, page_number=page,
                                   dpi=ocr_source.OCR_DPI)
    raw = src.raw_text()
    _text, lines, _rep = read_page(src, stats={})
    return raw, lines, src.applied


def run(skew_min=None):
    if skew_min is not None:
        ocr_source.SKEW_MIN = float(skew_min)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp)
        manifest = generate(out)
        report = {"skew_min": ocr_source.SKEW_MIN, "variants": {}}
        for v in manifest["variants"]:
            agg = {"pages": 0, "truth": 0, "read": 0, "passed": 0,
                   "lines_equal_reader": 0, "pages_detail": []}
            for p in v["pages"]:
                if p["origin"] != "scan":
                    continue
                raw, lines, applied = measure_page(out / v["file"], p["page"])
                rl = raw_lines(raw)
                geo = [" ".join(w["text"] for w in ln) for ln in lines]
                same = geo == [" ".join(w["text"] for w in ln) for ln in rl]
                d = {"page": p["page"], "applied": applied,
                     "lines_equal_reader": same, "fields": []}
                for c in p["cheques"]:
                    for f in FIELDS:
                        val = str(c["fields"].get(f) or "").strip()
                        if not val:
                            continue
                        read = matches_loosely(val, rl)
                        passed = read and matches_loosely(val, lines)
                        agg["truth"] += 1
                        agg["read"] += read
                        agg["passed"] += passed
                        if read and not passed:
                            d["fields"].append({"cheque": c["id"], "field": f,
                                                "value": val})
                agg["pages"] += 1
                agg["lines_equal_reader"] += same
                agg["pages_detail"].append(d)
            if agg["pages"]:
                agg["flagged_rate"] = round(
                    (agg["read"] - agg["passed"]) / agg["read"], 4) \
                    if agg["read"] else None
                report["variants"][v["file"][:-4]] = agg
        return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--label", required=True)
    ap.add_argument("--skew-min", type=float, default=None)
    ap.add_argument("--out", default=str(bs.TESTS_DIR / "reports"))
    a = ap.parse_args()
    t = time.time()
    rep = run(a.skew_min)
    rep["seconds"] = round(time.time() - t, 1)
    path = Path(a.out) / f"ocr_line_geometry_{a.label}.json"
    path.write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"SKEW_MIN={rep['skew_min']}  ({rep['seconds']}s)  -> {path.name}")
    print(f"{'variant':28s} pages truth  read passed flagged lines==reader")
    tot = {"truth": 0, "read": 0, "passed": 0}
    for name, a_ in rep["variants"].items():
        for k in tot:
            tot[k] += a_[k]
        fr = a_["flagged_rate"]
        print(f"{name:28s} {a_['pages']:5d} {a_['truth']:5d} {a_['read']:5d} "
              f"{a_['passed']:6d} {('%.1f%%' % (100 * fr)) if fr is not None else '-':>7s}"
              f" {a_['lines_equal_reader']}/{a_['pages']}")
    fr = (tot["read"] - tot["passed"]) / tot["read"] if tot["read"] else 0
    print(f"{'TOTAL':28s} {'':5s} {tot['truth']:5d} {tot['read']:5d} "
          f"{tot['passed']:6d} {100 * fr:6.1f}%")


if __name__ == "__main__":
    main()
