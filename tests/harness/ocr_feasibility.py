# -*- coding: utf-8 -*-
"""OCR feasibility: how close do an OCR engine's word boxes land to the truth?

MEASUREMENT, NOT A BUILD. No OcrPageSource exists; nothing here is imported by
production code. docs/OCR-READER-SEAM-DESIGN.md §10.1 asks whether any real
reader can meet EDGE_TOL = 1.0pt; this script produces the number.

    python -m tests.harness.ocr_feasibility                  # tesseract
    python -m tests.harness.ocr_feasibility --engine tesseract --dpi 300

For every gold PDF (all ten are digital text), each page is:

  1. read by PdfplumberSource             -> TRUTH words, points, top-left
  2. rendered to an image by poppler      -> the page as a scan would see it
  3. read by the OCR engine               -> words in PIXELS
  4. converted with the seam's own CoordinateSpace(unit="px", dpi=...) and
     normalise_words                      -> the conversion 15963ef tests
  5. matched against the truth by box overlap, and scored

⚠ BEST CASE, NOT A SCAN. A page rendered straight from its vector text has no
paper texture, no skew, no camera angle, no compression and no blur. A good
result here is necessary and not sufficient; a bad one is close to conclusive.

MATCHING. An edge joins a truth word and an OCR word when their boxes overlap
by at least OVERLAP_FRAC of the narrower box's width AND of the shorter box's
height. Connected components of that bipartite graph are classified:

    1 truth : 1 ocr, same text      CLEAN      -> edge errors are measured here
    1 truth : 1 ocr, different text MISREAD
    1 truth : n ocr                 SPLIT      (segmentation)
    n truth : 1 ocr                 MERGE      (segmentation)
    n truth : m ocr                 TANGLE     (segmentation)
    1 truth : 0 ocr                 MISSED
    0 truth : 1 ocr                 SPURIOUS

Adding an engine: write `ocr_<name>(image) -> (words_px, seconds)` returning
dicts with text/x0/x1/top/bottom in image pixels, top-left origin, and add it
to ENGINES. Everything after that is engine-blind.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

from tests.harness import bootstrap as bs

bs.bootstrap()

import pdfplumber  # noqa: E402
from pdf2image import convert_from_path  # noqa: E402

from text_layer import (EDGE_TOL, LINE_TOL, CoordinateSpace,  # noqa: E402
                        PdfplumberSource, normalise_words)

OVERLAP_FRAC = 0.3
EDGES = ("x0", "x1", "top", "bottom")
TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# ── engines ──────────────────────────────────────────────────────────────────

def ocr_tesseract(image):
    import pytesseract
    if Path(TESSERACT_EXE).exists():
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE
    t0 = time.perf_counter()
    d = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    secs = time.perf_counter() - t0
    words = []
    for i, level in enumerate(d["level"]):
        text = (d["text"][i] or "").strip()
        if level != 5 or not text:
            continue
        left, top = float(d["left"][i]), float(d["top"][i])
        words.append({"text": text, "x0": left, "x1": left + d["width"][i],
                      "top": top, "bottom": top + d["height"][i],
                      "conf": float(d["conf"][i]),
                      "_raw_px": (d["left"][i], d["top"][i],
                                  d["width"][i], d["height"][i])})
    return words, secs


def tesseract_version():
    import pytesseract
    if Path(TESSERACT_EXE).exists():
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE
    return str(pytesseract.get_tesseract_version())


ENGINES = {"tesseract": (ocr_tesseract, tesseract_version)}


# ── matching ─────────────────────────────────────────────────────────────────

def _overlaps(a, b):
    ox = min(a["x1"], b["x1"]) - max(a["x0"], b["x0"])
    oy = min(a["bottom"], b["bottom"]) - max(a["top"], b["top"])
    if ox <= 0 or oy <= 0:
        return False
    w = min(a["x1"] - a["x0"], b["x1"] - b["x0"]) or 1e-9
    h = min(a["bottom"] - a["top"], b["bottom"] - b["top"]) or 1e-9
    return ox >= OVERLAP_FRAC * w and oy >= OVERLAP_FRAC * h


def components(truth, ocr):
    """Connected components of the overlap graph: [(truth_idx, ocr_idx)]."""
    parent = list(range(len(truth) + len(ocr)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for ti, t in enumerate(truth):
        for oi, o in enumerate(ocr):
            if _overlaps(t, o):
                parent[find(ti)] = find(len(truth) + oi)
    groups = {}
    for i in range(len(parent)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for members in groups.values():
        ts = sorted(i for i in members if i < len(truth))
        os_ = sorted(i - len(truth) for i in members if i >= len(truth))
        out.append((ts, os_))
    return out


def classify(ts, os_, truth, ocr):
    if ts and not os_:
        return "missed"
    if os_ and not ts:
        return "spurious"
    if len(ts) == 1 and len(os_) == 1:
        return ("clean" if truth[ts[0]]["text"] == ocr[os_[0]]["text"]
                else "misread")
    if len(ts) == 1:
        return "split"
    if len(os_) == 1:
        return "merge"
    return "tangle"


def alone_on_line(t, truth):
    return not any(o is not t and min(o["bottom"], t["bottom"])
                   - max(o["top"], t["top"]) > 0 for o in truth)


# ── statistics ───────────────────────────────────────────────────────────────

def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * p / 100.0
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def dist(xs):
    if not xs:
        return {"n": 0}
    return {"n": len(xs), "min": min(xs), "median": pct(xs, 50),
            "p90": pct(xs, 90), "p99": pct(xs, 99), "max": max(xs),
            "within_EDGE_TOL": sum(1 for x in xs if x <= EDGE_TOL) / len(xs)}


def r(x, n=3):
    if isinstance(x, float):
        return round(x, n)
    if isinstance(x, dict):
        return {k: r(v, n) for k, v in x.items()}
    if isinstance(x, list):
        return [r(v, n) for v in x]
    return x


# ── run ──────────────────────────────────────────────────────────────────────

def run(engine, dpi):
    ocr_fn, version_fn = ENGINES[engine]
    labels = sorted(bs.LABELS_DIR.glob("*.json"))
    pdfs = [json.loads(p.read_text(encoding="utf-8"))["pdf"] for p in labels]

    counts = {k: 0 for k in ("clean", "misread", "split", "merge", "tangle",
                             "missed", "spurious")}
    truth_words_by_class = {k: 0 for k in counts}
    abs_err = {e: [] for e in EDGES}
    signed = {e: [] for e in EDGES}
    worst_edge = []
    far_clean = []            # text-equal but some edge beyond LINE_TOL
    seg_examples = {"split": [], "merge": [], "tangle": []}
    misread_examples = []
    missed_examples = []
    corner_probe = None
    flip_top_err, keep_top_err = [], []
    pages_out = []
    clean_pairs = []          # (doc, page, truth word, ocr word)

    for name in pdfs:
        path = bs.PDF_DIR / name
        with pdfplumber.open(path) as pdf:
            t0 = time.perf_counter()
            images = convert_from_path(str(path), dpi=dpi)
            render_s = (time.perf_counter() - t0) / max(len(images), 1)
            for pno, (page, img) in enumerate(zip(pdf.pages, images), 1):
                src = PdfplumberSource(page)
                truth = [w for w in src.words(size_aware=True)
                         if (w.get("text") or "").strip()]
                ocr_px, ocr_s = ocr_fn(img)
                # The seam's own conversion: pixels at a declared dpi,
                # top-left origin -> points, top-left.
                space = CoordinateSpace(unit="px", origin="top-left", dpi=dpi,
                                        height=img.height, width=img.width)
                ocr = normalise_words([dict(w) for w in ocr_px], space)

                expected_px = (page.width * dpi / 72.0,
                               page.height * dpi / 72.0)
                pc = {k: 0 for k in counts}
                for ts, os_ in components(truth, ocr):
                    cls = classify(ts, os_, truth, ocr)
                    counts[cls] += 1
                    pc[cls] += 1
                    truth_words_by_class[cls] += len(ts)
                    tt = [truth[i]["text"] for i in ts]
                    ot = [ocr[i]["text"] for i in os_]
                    if cls in seg_examples and len(seg_examples[cls]) < 25:
                        seg_examples[cls].append(
                            {"doc": name, "page": pno, "truth": tt, "ocr": ot})
                    if cls == "misread" and len(misread_examples) < 40:
                        misread_examples.append(
                            {"doc": name, "page": pno, "truth": tt[0],
                             "ocr": ot[0]})
                    if cls == "missed" and len(missed_examples) < 40:
                        missed_examples.append(
                            {"doc": name, "page": pno, "truth": tt})
                    if cls != "clean":
                        continue
                    t, o = truth[ts[0]], ocr[os_[0]]
                    errs = {}
                    for e in EDGES:
                        d = o[e] - t[e]
                        signed[e].append(d)
                        abs_err[e].append(abs(d))
                        errs[e] = abs(d)
                    worst_edge.append(max(errs.values()))
                    clean_pairs.append((name, pno, t, o))
                    if max(errs.values()) > LINE_TOL and len(far_clean) < 25:
                        far_clean.append({"doc": name, "page": pno,
                                          "text": t["text"], "err": errs})
                    # Origin check on the raw pixels, both hypotheses.
                    raw_top_pt = o["_raw_px"][1] * 72.0 / dpi
                    keep_top_err.append(abs(raw_top_pt - t["top"]))
                    flipped = page.height - raw_top_pt
                    flip_top_err.append(abs(flipped - t["top"]))
                    if (corner_probe is None and len(t["text"]) >= 6
                            and alone_on_line(t, truth)):
                        L, T, W, H = o["_raw_px"]
                        corner_probe = {
                            "doc": name, "page": pno, "text": t["text"],
                            "page_height_pt": page.height,
                            "truth_pt": {e: t[e] for e in EDGES},
                            "tesseract_raw_px": {"left": L, "top": T,
                                                 "width": W, "height": H},
                            "raw_px_as_pt": {
                                "left": L * 72 / dpi, "top": T * 72 / dpi,
                                "right": (L + W) * 72 / dpi,
                                "bottom": (T + H) * 72 / dpi},
                            "if_top_left_origin_top_pt": T * 72 / dpi,
                            "if_bottom_left_origin_top_pt":
                                page.height - (T + H) * 72 / dpi,
                        }
                pages_out.append({
                    "doc": name, "page": pno,
                    "truth_words": len(truth), "ocr_words": len(ocr),
                    "image_px": [img.width, img.height],
                    "expected_px": [round(expected_px[0], 2),
                                    round(expected_px[1], 2)],
                    "render_s": render_s, "ocr_s": ocr_s, "classes": pc})
                print(f"  {name} p{pno}: truth={len(truth)} ocr={len(ocr)} "
                      f"clean={pc['clean']} ocr={ocr_s:.2f}s", flush=True)

    # A CONSTANT offset is not noise. pdfplumber's box is the font's em box
    # (advance width x font size); an OCR box is the ink. Subtracting each
    # edge's median signed error leaves the part no calibration can remove.
    bias = {e: pct(signed[e], 50) for e in EDGES}
    residual = {e: dist([abs(d - bias[e]) for d in signed[e]]) for e in EDGES}

    # What EDGE_TOL actually governs: two words from ONE reader compared with
    # each other (repair_wrapped fuses on a shared right edge; check_placement
    # tests flush-right). Take every pair of clean words on different lines
    # whose TRUE right edges agree within 0.05pt — right-aligned by
    # construction — and ask how far apart OCR puts them.
    by_page = {}
    for name, pno, t, o in clean_pairs:
        by_page.setdefault((name, pno), []).append((t, o))
    pair_x1, pair_worst = [], []
    for (name, pno), items in by_page.items():
        for i in range(len(items)):
            ti, oi = items[i]
            for j in range(i + 1, len(items)):
                tj, oj = items[j]
                if abs(ti["x1"] - tj["x1"]) > 0.05:
                    continue
                if abs(ti["top"] - tj["top"]) < LINE_TOL:
                    continue
                d = abs(oi["x1"] - oj["x1"])
                pair_x1.append(d)
                pair_worst.append({"doc": name, "page": pno,
                                   "a": ti["text"], "b": tj["text"],
                                   "ocr_x1_gap": d})
    pair_worst = sorted(pair_worst, key=lambda p: -p["ocr_x1_gap"])[:15]

    total_truth = sum(p["truth_words"] for p in pages_out)
    ocr_times = [p["ocr_s"] for p in pages_out]
    report = {
        "engine": engine, "engine_version": version_fn(), "dpi": dpi,
        "EDGE_TOL": EDGE_TOL, "LINE_TOL": LINE_TOL,
        "overlap_frac": OVERLAP_FRAC,
        "caveat": "clean digitally-rendered pages: best case, not a scan",
        "documents": len(pdfs), "pages": len(pages_out),
        "truth_words": total_truth,
        "ocr_words": sum(p["ocr_words"] for p in pages_out),
        "components": counts,
        "truth_words_by_class": truth_words_by_class,
        "truth_word_fraction_by_class": {
            k: v / total_truth for k, v in truth_words_by_class.items()},
        "edge_error_abs_pt": {e: dist(abs_err[e]) for e in EDGES},
        "edge_error_signed_median_pt": {
            e: pct(signed[e], 50) for e in EDGES},
        "worst_edge_per_word_pt": dist(worst_edge),
        "edge_error_after_removing_median_bias_pt": residual,
        "right_aligned_pairs_ocr_x1_gap_pt": dist(pair_x1),
        "right_aligned_pairs_worst": pair_worst,
        "clean_but_beyond_LINE_TOL": far_clean,
        "origin_check": {
            "probe_word": corner_probe,
            "median_abs_top_err_pt_if_top_left": pct(keep_top_err, 50),
            "median_abs_top_err_pt_if_bottom_left": pct(flip_top_err, 50),
        },
        "timing_s_per_page": {"ocr": dist(ocr_times) | {
            "mean": statistics.mean(ocr_times), "total": sum(ocr_times)},
            "render_mean": statistics.mean(p["render_s"] for p in pages_out)},
        "segmentation_examples": seg_examples,
        "misread_examples": misread_examples,
        "missed_examples": missed_examples,
        "pages": pages_out,
    }
    report["timing_s_per_page"]["ocr"].pop("within_EDGE_TOL", None)
    return r(report)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--engine", default="tesseract", choices=sorted(ENGINES))
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    report = run(a.engine, a.dpi)
    out = Path(a.out) if a.out else (
        bs.REPORTS_DIR / f"ocr_feasibility_{a.engine}_{a.dpi}dpi.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
