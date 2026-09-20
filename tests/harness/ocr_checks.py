# -*- coding: utf-8 -*-
"""Cheque OCR field test: Tesseract text -> the PRODUCTION MICR parser.

MEASUREMENT, NOT A BUILD. Runs every image in tests/test_OCR/ (18 synthetic
cheques x clean / moderate / hard) through Tesseract, then through
`engine/micr.py` exactly as production calls it, and scores against the
per-cheque ground truth.

    python -m tests.harness.ocr_checks

WHAT IS PRODUCTION AND WHAT IS NOT
  production   find_micr_line, parse_micr, aba_is_valid, _TRANSIT_RE (micr.py)
  harness      the label regexes for payee / date / amount / words, the
               words->number converter, the check-number fallback. The engine
               has NONE of these: on the text path those fields are the
               model's job. They are the "straightforward matching" stand-in,
               and are reported as such.

⚠ SYNTHETIC CORPUS. The MICR band is printed as ASCII stand-ins in an ordinary
monospace font, NOT the E-13B typeface, so this does not measure reading E-13B.

ORACLE ROW. Every MICR measurement is also run on the EXACT printed string,
rebuilt from ground truth, so a parser failure is not reported as an OCR one.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

from tests.harness import bootstrap as bs

bs.bootstrap()

from PIL import Image  # noqa: E402

import micr  # noqa: E402
from micr import aba_is_valid, find_micr_line, parse_micr  # noqa: E402

CORPUS = bs.TESTS_DIR / "test_OCR"
TIERS = ("clean", "moderate", "hard")
TESSERACT_EXE = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
FIELDS = ("routing", "account", "check_number", "payee", "amount_numeral",
          "amount_words", "date", "bank")


PSM = None       # None = Tesseract's default (3); set by --psm


def ocr(path):
    import pytesseract
    if Path(TESSERACT_EXE).exists():
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE
    img = Image.open(path)
    t0 = time.perf_counter()
    config = f"--psm {PSM}" if PSM else ""
    text = pytesseract.image_to_string(img, config=config)
    return text, time.perf_counter() - t0


def printed_micr(gt):
    """The MICR band exactly as the corpus prints it (verified on the images:
    `C<serial>C  A<routing>A  <account>C`)."""
    return f"C{gt['check_number']}C  A{gt['routing_number']}A  {gt['account_number']}C"


# ── harness-only field recovery ──────────────────────────────────────────────

def _line_after(text, label_re):
    m = re.search(label_re + r"\s*(.+)", text, re.I)
    return m.group(1).strip() if m else ""


def recover(text):
    out = {}
    out["payee"] = _line_after(text, r"PAY\s+TO\s+THE\s+ORDER\s+OF\s*:?")
    m = re.search(r"Date\s*:?\s*(\d{1,2}/\d{1,2}/\d{4})", text, re.I)
    out["date"] = m.group(1) if m else ""
    m = re.search(r"\$\s*([\d,]+\.\d{2})", text)
    out["amount_numeral"] = m.group(1) if m else ""
    m = re.search(r"^(.*?)\s*DOLLARS", text, re.I | re.M)
    out["amount_words"] = m.group(1).strip() if m else ""
    # check number: a line that is only a 6-digit number, else the leading
    # on-us field of the MICR band.
    m = re.search(r"^\s*(\d{6})\s*$", text, re.M)
    if m:
        out["check_number_fallback"] = m.group(1)
    else:
        m = re.search(r"C(\d{3,})C", find_micr_line(text) or "")
        out["check_number_fallback"] = m.group(1) if m else ""
    return out


_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve "
    "thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split())}
_TENS = {w: 10 * i for i, w in enumerate(
    "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()) if w != "_"}


def words_to_amount(s):
    """'three thousand five hundred seventy-two and 78/100' -> 3572.78, or None."""
    s = str(s or "").casefold().replace("-", " ")
    m = re.match(r"^(.*?)\s+and\s+(\d{1,2})\s*/\s*100\b", s)
    if not m:
        return None
    total, cur = 0, 0
    for w in m.group(1).split():
        if w in _UNITS:
            cur += _UNITS[w]
        elif w in _TENS:
            cur += _TENS[w]
        elif w == "hundred":
            cur *= 100
        elif w == "thousand":
            total += cur * 1000
            cur = 0
        else:
            return None                      # an unreadable word: no verdict
    return round(total + cur + int(m.group(2)) / 100.0, 2)


def numeral_to_amount(s):
    try:
        return round(float(str(s).replace(",", "")), 2)
    except ValueError:
        return None


def norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


# ── MICR through production code ─────────────────────────────────────────────

def micr_view(text):
    line = find_micr_line(text)
    parsed = parse_micr(line) if line else {}
    m = micr._TRANSIT_RE.search(line) if line else None
    transit = m.group(1) if m else ""
    verdict = ("no read" if not transit
               else "valid" if aba_is_valid(transit) else "invalid")
    return {"line": line, "parsed": parsed, "transit": transit,
            "verdict": verdict}


def last_lines(text, n=2):
    return [ln for ln in text.splitlines() if ln.strip()][-n:]


# ── run ──────────────────────────────────────────────────────────────────────

def score(gt, text):
    mv = micr_view(text)
    rec = recover(text)
    got = {
        "routing": mv["parsed"].get("routing_number", ""),
        "account": mv["parsed"].get("account_number", ""),
        "check_number": mv["parsed"].get("serial_number", ""),
        "check_number_fallback": rec["check_number_fallback"],
        "payee": rec["payee"], "amount_numeral": rec["amount_numeral"],
        "amount_words": rec["amount_words"], "date": rec["date"],
        "bank": gt["bank"] if norm(gt["bank"]) in norm(text) else "",
    }
    want = {
        "routing": gt["routing_number"] if gt["routing_checksum_valid"] else "",
        "account": gt["account_number"], "check_number": gt["check_number"],
        "check_number_fallback": gt["check_number"], "payee": gt["payee"],
        "amount_numeral": gt["amount_numeral"],
        "amount_words": gt["amount_words_shown"], "date": gt["date"],
        "bank": gt["bank"],
    }
    ok = {k: norm(got[k]) == norm(want[k]) for k in want}
    # routing is "correct" for an invalid-checksum cheque when production
    # reports NOTHING — parse_micr withholds a failing routing number.
    # The raw transit read is scored separately below.
    ok["routing_transit_read"] = mv["transit"] == gt["routing_number"]

    n = numeral_to_amount(rec["amount_numeral"]) if rec["amount_numeral"] else None
    w = words_to_amount(rec["amount_words"]) if rec["amount_words"] else None
    if n is None or w is None:
        mismatch = "undecidable"
    else:
        mismatch = "mismatch" if abs(n - w) > 0.001 else "agree"
    truth_mm = "mismatch" if not gt["amount_words_matches_numeral"] else "agree"

    want_verdict = "valid" if gt["routing_checksum_valid"] else "invalid"
    return {"got": got, "want": want, "ok": ok, "micr": mv,
            "micr_located": bool(mv["line"]),
            "checksum_verdict": mv["verdict"],
            "checksum_correct": mv["verdict"] == want_verdict,
            "mismatch": mismatch, "mismatch_truth": truth_mm,
            "mismatch_correct": mismatch == truth_mm,
            "tail_ocr_lines": last_lines(text)}


def rate(rows, key):
    rows = list(rows)
    return (sum(1 for r in rows if key(r)), len(rows))


def main(argv=None):
    import argparse
    global PSM
    ap = argparse.ArgumentParser()
    ap.add_argument("--psm", type=int, default=None,
                    help="Tesseract page-segmentation mode; default = engine default")
    PSM = ap.parse_args(argv).psm
    idx = json.loads((CORPUS / "_index.json").read_text(encoding="utf-8"))
    results = []
    for gt in idx:
        oracle = score(gt, printed_micr(gt))
        for tier in TIERS:
            text, secs = ocr(CORPUS / gt["files"][tier])
            s = score(gt, text)
            results.append({"id": gt["id"], "template": gt["template"],
                            "tier": tier, "ocr_s": secs, "ocr_text": text,
                            "oracle_micr": {k: oracle[k] for k in (
                                "micr_located", "checksum_verdict")}
                            | {"parsed": oracle["micr"]["parsed"]},
                            **s})
            print(f"  {gt['id']} {tier:8s} micr={'Y' if s['micr_located'] else 'N'} "
                  f"chk={s['checksum_verdict']:8s} mm={s['mismatch']:11s} "
                  f"{sum(s['ok'].values())}/{len(s['ok'])} ok  {secs:.2f}s",
                  flush=True)

    fields = list(results[0]["ok"])
    summary = {"by_tier": {}, "by_template_tier": {}, "oracle": {}}
    for tier in TIERS:
        rs = [r for r in results if r["tier"] == tier]
        summary["by_tier"][tier] = {
            "fields": {f: rate(rs, lambda r, f=f: r["ok"][f]) for f in fields},
            "micr_located": rate(rs, lambda r: r["micr_located"]),
            "checksum_correct": rate(rs, lambda r: r["checksum_correct"]),
            "checksum_verdicts": {r["id"]: r["checksum_verdict"] for r in rs},
            "mismatch_correct": rate(rs, lambda r: r["mismatch_correct"]),
            "mismatch_outcomes": {r["id"]: r["mismatch"] for r in rs},
            "ocr_s_mean": sum(r["ocr_s"] for r in rs) / len(rs),
        }
        for tpl in sorted({r["template"] for r in rs}):
            ts = [r for r in rs if r["template"] == tpl]
            summary["by_template_tier"].setdefault(tpl, {})[tier] = {
                "cheques": len(ts),
                "field_hits": rate(((r, f) for r in ts for f in FIELDS),
                                   lambda rf: rf[0]["ok"][rf[1]]),
                "micr_located": rate(ts, lambda r: r["micr_located"]),
                "per_field": {f: rate(ts, lambda r, f=f: r["ok"][f])
                              for f in fields},
            }
    clean_ids = [r for r in results if r["tier"] == "clean"]
    summary["oracle"] = {
        "micr_located": rate(clean_ids, lambda r: r["oracle_micr"]["micr_located"]),
        "parsed_examples": {r["id"]: r["oracle_micr"]["parsed"]
                            for r in clean_ids[:3]},
        "account_equals_gt": rate(
            (r for r in clean_ids),
            lambda r: r["oracle_micr"]["parsed"].get("account_number")
            == r["want"]["account"]),
        "serial_present": rate(
            clean_ids, lambda r: "serial_number" in r["oracle_micr"]["parsed"]),
    }

    summary["psm"] = PSM or "default(3)"
    out = bs.REPORTS_DIR / ("ocr_checks_tesseract.json" if not PSM
                            else f"ocr_checks_tesseract_psm{PSM}.json")
    out.write_text(json.dumps({"summary": summary, "results": results},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
