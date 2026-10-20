#!/usr/bin/env python3
"""
Builds the SCAN-VARIANT PDF corpus: cheques composed into the file shapes a
real accounting workflow produces, with ground truth taken from the generator's
own inputs (never from engine output).

    python tests/fixtures/make_scan_variants.py --out <dir>             # writes PDFs + manifest.json
    python tests/fixtures/make_scan_variants.py --out <dir> --verify    # also checks every PDF against its manifest
    python tests/fixtures/make_scan_variants.py --out <dir> --seed 7

WHY THIS EXISTS. `tests/test_OCR/` holds 18 single cheques as images. The shapes
that matter for OCR provenance and cheque batches are not single images:

  scan_*          image-only pages, no text layer (a scanner's output)
  preocr_*        the same image PLUS an invisible text layer (a scanner or MFP
                  that ran its own OCR). The pipeline treats such a page as
                  native text today; `preocr_garbled` has a deliberately wrong
                  layer so a test can show a wrong-but-"native" value
  mixed_*         digital pages and scanned pages in ONE file
  *_up            several cheques on one page
  scan_blank      a page that yields zero OCR words
  scan_rotated    pages fed in sideways / upside down

GROUND TRUTH. Every field in manifest.json comes from tests/test_OCR/_index.json
(the single source of truth for the 18 cheques) or from this script's own
corruption record. Gold is never regenerated from engine output.

SYNTHETIC. These are generated documents. They support mechanism and regression
tests; they cannot support an accuracy claim about real client scans.

NOT COMMITTED AS BINARIES. The PDFs are deterministic (fixed seed, no dates, no
document IDs), so regenerate them into a temp or ignored directory instead of
committing ~3 MB of binaries.

DEPENDENCIES: Pillow only (already pinned). PDFs are written by hand so no
PDF-writing library is added. `--verify` additionally needs pdfplumber.

LIMITS, stated so nobody over-reads the fixtures:
  * The invisible text layer's positions are APPROXIMATE (fractions of the
    cheque box) and do not line up with the image's real glyphs. That is
    realistic for badly registered embedded OCR, but a highlight-alignment test
    must not use these.
  * "Digital" pages are plain text pages built from the same fields; they are
    not a faithful cheque graphic.
  * Page size is US Letter at 300 dpi.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import sys
from pathlib import Path

from PIL import Image

DPI = 300
PAGE_PX = (2550, 3300)                      # US Letter at 300 dpi
PT = 72.0 / DPI                             # pixels -> PDF points
DEFAULT_SEED = 20261020
JPEG_QUALITY = 75

# Cheques deliberately carrying a bad routing checksum or a numeral/words
# mismatch (see tests/test_OCR/README.md). Kept out of ordinary batches.
TRAPS = ["chk_007", "chk_009", "chk_014", "chk_016"]
FIELDS = ["bank", "payee", "check_number", "date", "amount_numeral",
          "amount_words_shown", "routing_number", "account_number", "memo"]
CONFUSE = {"8": "3", "3": "8", "0": "O", "1": "l", "5": "S", "2": "Z",
           "6": "G", "9": "g"}


# ── a minimal, deterministic PDF writer ──────────────────────────────────────

def _esc(text: str) -> bytes:
    text = text.encode("latin-1", "replace").decode("latin-1")
    return (text.replace("\\", "\\\\").replace("(", "\\(")
            .replace(")", "\\)").encode("latin-1"))


def _text_ops(lines, render_mode: int) -> bytes:
    """lines: (x_pt, y_pt, size, text). render_mode 0 visible, 3 invisible."""
    out = [b"BT", f"{render_mode} Tr".encode()]
    for x, y, size, text in lines:
        out.append(f"/F1 {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm (".encode()
                   + _esc(text) + b") Tj")
    out.append(b"ET")
    return b"\n".join(out)


def build_pdf(pages: list[dict]) -> bytes:
    """pages: {w_pt, h_pt, jpeg (bytes|None), jpeg_px (w,h), ops (bytes),
    rotate (int)}. No dates, no /ID: same input -> same bytes."""
    objs: dict[int, bytes] = {}
    objs[3] = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
               b"/Encoding /WinAnsiEncoding >>")
    nxt, kids = 4, []
    for p in pages:
        page_n, content_n = nxt, nxt + 1
        img_n = nxt + 2 if p.get("jpeg") else None
        nxt += 3 if img_n else 2
        kids.append(page_n)
        content = b""
        if img_n:
            content += (f"q {p['w_pt']:.2f} 0 0 {p['h_pt']:.2f} 0 0 cm "
                        f"/Im0 Do Q\n").encode()
            iw, ih = p["jpeg_px"]
            objs[img_n] = (
                f"<< /Type /XObject /Subtype /Image /Width {iw} /Height {ih} "
                f"/ColorSpace /DeviceGray /BitsPerComponent 8 "
                f"/Filter /DCTDecode /Length {len(p['jpeg'])} >>\nstream\n"
            ).encode() + p["jpeg"] + b"\nendstream"
        content += p.get("ops", b"")
        objs[content_n] = (f"<< /Length {len(content)} >>\nstream\n".encode()
                           + content + b"\nendstream")
        res = "/Font << /F1 3 0 R >>"
        if img_n:
            res += f" /XObject << /Im0 {img_n} 0 R >>"
        rot = f" /Rotate {p['rotate']}" if p.get("rotate") else ""
        objs[page_n] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {p['w_pt']:.2f} "
            f"{p['h_pt']:.2f}] /Contents {content_n} 0 R "
            f"/Resources << {res} >>{rot} >>").encode()
    objs[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objs[2] = (f"<< /Type /Pages /Count {len(kids)} /Kids ["
               + " ".join(f"{k} 0 R" for k in kids) + "] >>").encode()
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for n in sorted(objs):
        offsets[n] = len(out)
        out += f"{n} 0 obj\n".encode() + objs[n] + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for n in sorted(objs):
        out += f"{offsets[n]:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)


def jpeg_bytes(im: Image.Image) -> bytes:
    buf = io.BytesIO()
    im.convert("L").save(buf, "JPEG", quality=JPEG_QUALITY, dpi=(DPI, DPI))
    return buf.getvalue()


# ── corpus ───────────────────────────────────────────────────────────────────

def load_records(repo: Path) -> dict:
    ocr_dir = repo / "tests" / "test_OCR"
    idx = json.loads((ocr_dir / "_index.json").read_text(encoding="utf-8"))
    return {r["id"]: r for r in idx}, ocr_dir


def truth(rec: dict) -> dict:
    t = {f: ("" if rec.get(f) is None else rec[f]) for f in
         ["bank", "payee", "check_number", "date", "amount_numeral",
          "routing_number", "account_number", "memo"]}
    t["amount_words_shown"] = rec["amount_words_shown"]
    t["intentional_invalid_checksum"] = bool(
        rec.get("intentional_invalid_checksum_test_case"))
    t["intentional_words_numeral_mismatch"] = bool(
        rec.get("intentional_mismatch_test_case"))
    t["routing_checksum_valid"] = bool(rec.get("routing_checksum_valid"))
    return t


def compose_page(images, rng):
    """Paste cheque images onto a white Letter page. Returns (page, boxes)."""
    page = Image.new("L", PAGE_PX, 255)
    y = 120 + rng.randint(-20, 40)
    boxes = []
    for im in images:
        im = im.convert("L")
        if y + im.height > PAGE_PX[1] - 60:
            raise ValueError("cheques do not fit on one page at 300 dpi")
        x = (PAGE_PX[0] - im.width) // 2 + rng.randint(-40, 40)
        page.paste(im, (x, y))
        boxes.append({"x": x, "y": y, "w": im.width, "h": im.height})
        y += im.height + 120
    return page, boxes


def corrupt_digits(s: str, rng, force=False) -> str:
    out, changed = [], False
    for ch in s:
        r = rng.random()
        if ch in CONFUSE and r < 0.22:
            out.append(CONFUSE[ch]); changed = True
        elif ch.isdigit() and r > 0.97:
            changed = True                    # a dropped digit
        else:
            out.append(ch)
    res = "".join(out)
    if force and not changed:
        for i, ch in enumerate(res):
            if ch in CONFUSE:
                return res[:i] + CONFUSE[ch] + res[i + 1:]
    return res


def layer_values(rec, rng, garbled):
    """What the embedded text layer says, per field."""
    t = truth(rec)
    num = t["amount_numeral"]
    vals = {
        "bank": t["bank"], "payee": t["payee"], "date": t["date"],
        "check_number": t["check_number"], "amount_numeral": "$" + num,
        "amount_words_shown": t["amount_words_shown"], "memo": t["memo"],
        "routing_number": t["routing_number"],
        "account_number": t["account_number"],
    }
    if garbled:
        vals["payee"] = corrupt_digits(t["payee"], rng)     # letters rarely change
        vals["amount_numeral"] = "$" + corrupt_digits(num, rng, force=True)
        vals["routing_number"] = corrupt_digits(t["routing_number"], rng, True)
        vals["account_number"] = corrupt_digits(t["account_number"], rng, True)
        vals["check_number"] = corrupt_digits(t["check_number"], rng)
    micr = (f"A{vals['routing_number']}A C{vals['account_number']}C "
            f"{vals['check_number']}D")
    return vals, micr


# fraction-of-cheque-box anchors for the (approximate) invisible text layer
ANCHORS = {"bank": (0.06, 0.12), "date": (0.70, 0.14), "payee": (0.12, 0.38),
           "amount_numeral": (0.78, 0.40), "amount_words_shown": (0.10, 0.52),
           "memo": (0.08, 0.80), "check_number": (0.82, 0.08)}


def preocr_ops(rec, box, rng, garbled):
    vals, micr = layer_values(rec, rng, garbled)
    h_pt = PAGE_PX[1] * PT
    lines = []
    for f, (fx, fy) in ANCHORS.items():
        x = (box["x"] + fx * box["w"]) * PT
        y = h_pt - (box["y"] + fy * box["h"]) * PT
        lines.append((x, y, 10, str(vals[f])))
    lines.append(((box["x"] + 0.06 * box["w"]) * PT,
                  h_pt - (box["y"] + 0.93 * box["h"]) * PT, 10, micr))
    t = truth(rec)
    entries = []
    for f in ["bank", "payee", "date", "check_number", "amount_numeral",
              "amount_words_shown", "memo", "routing_number", "account_number"]:
        shown = vals[f]
        want = t[f]
        entries.append({"field": f, "in_layer": shown, "truth": want,
                        "matches_truth": shown.lstrip("$") == str(want)})
    return _text_ops(lines, 3), {"micr_line_in_layer": micr, "fields": entries}


def digital_ops(rec):
    t = truth(rec)
    lines, y = [], 700
    rows = [
        ("CHEQUE", 18), (f"No. {t['check_number']}    Date: {t['date']}", 12),
        (f"Bank: {t['bank']}", 12),
        (f"Pay to the order of: {t['payee']}", 12),
        (f"Amount: ${t['amount_numeral']}", 12),
        (f"Amount in words: {t['amount_words_shown']}", 12),
        (f"Memo: {t['memo']}", 12),
        (f"A{t['routing_number']}A C{t['account_number']}C "
         f"{t['check_number']}D", 12),
    ]
    for text, size in rows:
        lines.append((72, y, size, text)); y -= 26
    return _text_ops(lines, 0)


# ── variants ─────────────────────────────────────────────────────────────────
# kind: scan | digital | preocr_good | preocr_garbled | blank
V = lambda **k: k
NORMAL = ["chk_001", "chk_002", "chk_003", "chk_004", "chk_005", "chk_006",
          "chk_008", "chk_010", "chk_011", "chk_012", "chk_013", "chk_015"]

VARIANTS = [
    V(name="scan_only_single", purpose="One scanned cheque, one page, no text layer.",
      pages=[V(kind="scan", cheques=[("chk_001", "moderate")])]),
    V(name="scan_hard_single", purpose="One hard-tier scan (6-14 degree skew, noise).",
      pages=[V(kind="scan", cheques=[("chk_004", "hard")])]),
    V(name="scan_batch_10pages",
      purpose="Ten cheques, one per page, scan only: the '10 cheques in a PDF' case.",
      pages=[V(kind="scan", cheques=[(c, "moderate")]) for c in
             ["chk_001", "chk_002", "chk_003", "chk_004", "chk_005",
              "chk_006", "chk_008", "chk_010", "chk_011", "chk_012"]]),
    V(name="scan_two_and_three_up",
      purpose="Several cheques on ONE page (2 then 3): document boundaries inside a page.",
      pages=[V(kind="scan", cheques=[("chk_001", "moderate"), ("chk_002", "moderate")]),
             V(kind="scan", cheques=[("chk_003", "moderate"), ("chk_005", "moderate"),
                                     ("chk_006", "moderate")])]),
    V(name="scan_traps_4pages",
      purpose="The four deliberately bad cheques (invalid ABA checksum; numeral/words mismatch).",
      pages=[V(kind="scan", cheques=[(c, "moderate")]) for c in TRAPS]),
    V(name="scan_blank", purpose="A blank scanned page: OCR yields zero words.",
      pages=[V(kind="blank", cheques=[])]),
    V(name="scan_rotated_pages",
      purpose="Pages fed in sideways / upside down (OSD path). rotate_ccw is how far the page image was turned.",
      pages=[V(kind="scan", cheques=[("chk_001", "moderate")], rotate_ccw=90),
             V(kind="scan", cheques=[("chk_002", "moderate")], rotate_ccw=180),
             V(kind="scan", cheques=[("chk_003", "moderate")], rotate_ccw=270)]),
    V(name="scan_pdf_rotate_attr",
      purpose="A scan whose page carries a /Rotate 90 attribute.",
      pages=[V(kind="scan", cheques=[("chk_006", "moderate")], pdf_rotate_attr=90)]),
    V(name="preocr_good",
      purpose="Scans carrying an embedded, ACCURATE invisible text layer (scanner OCR).",
      pages=[V(kind="preocr_good", cheques=[("chk_001", "moderate")]),
             V(kind="preocr_good", cheques=[("chk_002", "moderate")])]),
    V(name="preocr_garbled",
      purpose="Scans whose embedded text layer is WRONG (digit confusions/drops). Must not yield high confidence.",
      pages=[V(kind="preocr_garbled", cheques=[("chk_001", "moderate")]),
             V(kind="preocr_garbled", cheques=[("chk_002", "moderate")])]),
    V(name="mixed_digital_then_scan", purpose="Page 1 native text, page 2 a scan.",
      pages=[V(kind="digital", cheques=[("chk_008", None)]),
             V(kind="scan", cheques=[("chk_001", "moderate")])]),
    V(name="mixed_scan_then_digital", purpose="Page 1 a scan, page 2 native text.",
      pages=[V(kind="scan", cheques=[("chk_002", "moderate")]),
             V(kind="digital", cheques=[("chk_010", None)])]),
    V(name="mixed_with_blank_middle",
      purpose="Native page, blank scanned page, scanned cheque.",
      pages=[V(kind="digital", cheques=[("chk_011", None)]),
             V(kind="blank", cheques=[]),
             V(kind="scan", cheques=[("chk_003", "moderate")])]),
    V(name="digital_batch_3pages", purpose="Control: three native-text cheque pages.",
      pages=[V(kind="digital", cheques=[(c, None)]) for c in
             ["chk_012", "chk_013", "chk_015"]]),
]

ORIGIN = {"scan": "scan", "blank": "scan", "digital": "native",
          "preocr_good": "pre_ocr", "preocr_garbled": "pre_ocr"}
LAYER = {"scan": "none", "blank": "none", "digital": "native",
         "preocr_good": "embedded_accurate", "preocr_garbled": "embedded_wrong"}


def build_variant(spec, records, ocr_dir, seed):
    rng = random.Random(f"{seed}:{spec['name']}")
    pdf_pages, man_pages, documents = [], [], []
    for pno, ps in enumerate(spec["pages"], start=1):
        kind = ps["kind"]
        w_pt, h_pt = PAGE_PX[0] * PT, PAGE_PX[1] * PT
        entry = {"page": pno, "kind": kind, "origin": ORIGIN[kind],
                 "text_layer": LAYER[kind],
                 "expect_ocr": kind in ("scan", "blank"),
                 "expected_review_required": kind != "digital",
                 "blank": kind == "blank", "cheques": []}
        page = {"w_pt": w_pt, "h_pt": h_pt, "ops": b""}
        if kind == "digital":
            cid = ps["cheques"][0][0]
            page["ops"] = digital_ops(records[cid])
            entry["cheques"].append({"id": cid, "tier": None,
                                     "fields": truth(records[cid])})
            documents.append({"pages": [pno], "cheque_ids": [cid]})
        else:
            if kind == "blank":
                img, boxes = Image.new("L", PAGE_PX, 255), []
            else:
                ims = [Image.open(ocr_dir / records[c]["files"][t])
                       for c, t in ps["cheques"]]
                img, boxes = compose_page(ims, rng)
            rot = ps.get("rotate_ccw", 0)
            if rot:
                img = img.rotate(rot, expand=True, fillcolor=255)
                w_pt, h_pt = img.width * PT, img.height * PT
                page.update(w_pt=w_pt, h_pt=h_pt)
                entry["page_turned_ccw_deg"] = rot
            page["jpeg"], page["jpeg_px"] = jpeg_bytes(img), img.size
            entry["image_px"] = list(img.size)
            for (cid, tier), box in zip(ps["cheques"], boxes):
                c = {"id": cid, "tier": tier, "fields": truth(records[cid]),
                     "box_px_before_rotation": box}
                if kind.startswith("preocr"):
                    ops, layer = preocr_ops(records[cid], box, rng,
                                            kind == "preocr_garbled")
                    page["ops"] += ops
                    c["text_layer"] = layer
                entry["cheques"].append(c)
                documents.append({"pages": [pno], "cheque_ids": [cid]})
        if ps.get("pdf_rotate_attr"):
            page["rotate"] = ps["pdf_rotate_attr"]
            entry["pdf_rotate_attr"] = ps["pdf_rotate_attr"]
        pdf_pages.append(page)
        man_pages.append(entry)
    return build_pdf(pdf_pages), {
        "file": f"{spec['name']}.pdf", "purpose": spec["purpose"],
        "page_count": len(pdf_pages), "pages": man_pages,
        "documents_in_reading_order": documents,
    }


def verify(out: Path, manifest: dict) -> list[str]:
    import pdfplumber
    bad = []
    for v in manifest["variants"]:
        with pdfplumber.open(out / v["file"]) as pdf:
            if len(pdf.pages) != v["page_count"]:
                bad.append(f"{v['file']}: page count {len(pdf.pages)}")
                continue
            for pg, exp in zip(pdf.pages, v["pages"]):
                words = pg.extract_words()
                cover = 0.0
                for im in pg.images:
                    cover = max(cover, (im["x1"] - im["x0"]) * (im["bottom"] - im["top"])
                                / (pg.width * pg.height))
                tag = f"{v['file']} p{exp['page']}"
                if exp["text_layer"] in ("none",) and words:
                    bad.append(f"{tag}: scan page has a text layer")
                if exp["text_layer"].startswith("embedded") and not words:
                    bad.append(f"{tag}: pre-OCR page has no text layer")
                if exp["text_layer"] == "native" and (not words or pg.images):
                    bad.append(f"{tag}: native page should be text only")
                if exp["origin"] != "native" and cover < 0.9:
                    bad.append(f"{tag}: image covers only {cover:.0%} of the page")
    return bad


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    here = Path(__file__).resolve()
    ap.add_argument("--repo", type=Path, default=here.parents[2])
    ap.add_argument("--out", type=Path, required=True,
                    help="output directory; required so a run can never "
                         "write generated PDFs into the repo by default")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()

    records, ocr_dir = load_records(a.repo)
    a.out.mkdir(parents=True, exist_ok=True)
    manifest = {"generator": "tests/fixtures/make_scan_variants.py", "version": 1,
                "seed": a.seed, "dpi": DPI, "source": "tests/test_OCR/_index.json",
                "synthetic": True, "variants": []}
    for spec in VARIANTS:
        data, mv = build_variant(spec, records, ocr_dir, a.seed)
        (a.out / mv["file"]).write_bytes(data)
        mv["sha256"] = hashlib.sha256(data).hexdigest()
        manifest["variants"].append(mv)
        print(f"{mv['file']:34s} {mv['page_count']:>2} pages  {len(data)/1024:7.0f} KiB")
    (a.out / "manifest.json").write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    if a.verify:
        bad = verify(a.out, manifest)
        for b in bad:
            print("MISMATCH:", b)
        print("verify:", "FAILED" if bad else "ok")
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
