"""Synthetic multi-locale documents through the engine (Parts 1.8 and 1.9).

tests/fixtures/make_locale_fixtures.py builds bank statements in six styles,
invoices with sales tax / VAT / GST, a payslip and a receipt, plus corrupted
variants. Each is read by the REAL pipeline — text layer, grounding, the
locale readers, the validators — with a model stub answering FROM THE TRUTH
and quoting the exact printed line. So what is measured is the engine, not a
model: every value must come out, clean documents must raise no defect flag,
and each corruption must raise its own flag.

`test_report` prints the table per locale and family (pytest -s).
"""
from __future__ import annotations

import contextlib
import io
import json
import re
import sys
from types import SimpleNamespace

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()
sys.path.insert(0, str(bs.TESTS_DIR / "fixtures"))

import make_locale_fixtures as M  # noqa: E402

DOCS = M.documents()
CLEAN = [k for k, d in DOCS.items() if not d.get("corruption")]
CORRUPT = [k for k, d in DOCS.items() if d.get("corruption")]
DEFECTS = {"balance_mismatch", "row_count_mismatch", "currency_mismatch", "totals_mismatch",
           "payslip_mismatch", "receipt_mismatch", "gstin_invalid"}


class _Resp:
    def __init__(self, obj):
        self.success, self.parsed_json, self.raw_text = True, obj, json.dumps(obj)
        self.model_used, self.tokens_used, self.error = "truth-stub", 0, ""


def truth_stub(doc):
    """Answers the slot prompt from the document's truth, quoting the line."""
    def extract(text="", image_b64="", prompt="", **kw):
        fields = {}
        for sid, label in re.findall(r'^\s+(F\d+): .*the value on the row labelled "(.*)"\s*$', prompt, re.M):
            v = doc["fields"].get(label)
            fields[sid] = ({"value": v, "source": f"{label}: {v}", "page": 1}
                           if v is not None else {"value": "", "source": "", "page": 0})
        tables = {}
        for name in re.findall(r'^TABLE "(.+?)"', prompt, re.M):
            tables[name] = [{"cells": dict(r), "page": 1,
                             "source": "   ".join(r[c] if r[c] else "-" for c in doc["columns"])}
                            for r in doc["rows"]]
        return _Resp({"fields": fields, "tables": tables})
    return SimpleNamespace(llm=SimpleNamespace(extract=extract))


def run(name, form="native", tmp=None):
    import extractor
    d = DOCS[name]
    pdf = {"native": M.native_pdf, "scan": M.scan_pdf}[form](d)
    path = tmp / f"{name}.{form}.pdf"
    path.write_bytes(pdf)
    with contextlib.redirect_stdout(io.StringIO()):
        res = extractor.run_extraction(truth_stub(d), path, json.loads(json.dumps(d["template"])))
    return res[0].extracted_data


def reasons(ed):
    out = set()
    for p in (ed.get("field_provenance") or {}).values():
        out |= set(p.get("review_reasons") or [])
    for k, rows in ed.items():
        if k.endswith("_rows") and isinstance(rows, list):
            for r in rows:
                out |= set(r.get("_review_reasons") or [])
    return out


def score(name, ed):
    d = DOCS[name]
    vals = ed.get("extracted_fields") or {}
    got_fields = sum(1 for v in d["fields"].values() if v in vals.values())
    rows = ed.get("rows_rows") or []
    keys = d["columns"]
    good_rows = sum(1 for want, r in zip(d["rows"], rows)
                    if all(str(r.get(c, "")) == want[c] for c in keys))
    return got_fields, len(d["fields"]), len(rows), len(d["rows"]), good_rows


@pytest.mark.parametrize("name", CLEAN)
def test_clean_documents_come_out_whole_and_raise_no_defect(name, tmp_path):
    ed = run(name, tmp=tmp_path)
    f_got, f_all, r_got, r_all, r_good = score(name, ed)
    assert (f_got, r_got, r_good) == (f_all, r_all, r_all), (name, f_got, f_all, r_got, r_all, r_good)
    assert not (reasons(ed) & DEFECTS), (name, reasons(ed) & DEFECTS)


@pytest.mark.parametrize("name", CORRUPT)
def test_each_corruption_raises_its_own_flag(name, tmp_path):
    ed = run(name, tmp=tmp_path)
    want = set(DOCS[name]["expect_flags"])
    assert want <= reasons(ed), (name, want, reasons(ed))


@pytest.mark.parametrize("name", ["statement_in", "statement_jp", "statement_eu"])
def test_locale_specific_notation_is_read_not_flagged(name, tmp_path):
    ed = run(name, tmp=tmp_path)
    assert not (reasons(ed) & {"number_ambiguous", "date_ambiguous", "minor_units_mismatch"})


def test_the_gstin_invoice_passes_its_identifier_check(tmp_path):
    d = json.loads(json.dumps(DOCS["invoice_in_gst"]))
    r = [k for k, c in d["template"]["layout"]["cells"].items() if c.get("value") == "GSTIN"][0]
    row = r.split(",")[0]
    d["template"]["layout"]["cells"][f"{row},1"] = {"value": "", "id_type": "gstin"}
    DOCS["_gst_typed"] = d
    try:
        ed = run("_gst_typed", tmp=tmp_path)
    finally:
        del DOCS["_gst_typed"]
    checks = [p.get("id_check") for p in ed["field_provenance"].values() if p.get("id_type")]
    assert checks == ["pass"]


def test_the_password_protected_copy_opens_with_its_password(tmp_path):
    from app.services.job_worker import _open_locked_pdf
    p = tmp_path / "locked.pdf"
    p.write_bytes(M.locked_pdf(DOCS["statement_uk"]))
    store = SimpleNamespace(temp_dir=tmp_path)
    opened, copy, why = _open_locked_pdf(store, p, M.PASSWORD)
    assert why is None and copy is not None
    _, _, why = _open_locked_pdf(store, p, "wrong")
    assert "incorrect" in why


def test_report(tmp_path, capsys):
    """The table per locale and family (native; a degraded scan of each
    statement too: its values are OCR readings, so they need review)."""
    lines = [f"{'document':34} {'fields':>9} {'rows':>9} {'rows ok':>7}  flags"]
    for name in DOCS:
        ed = run(name, tmp=tmp_path)
        f_got, f_all, r_got, r_all, r_good = score(name, ed)
        flags = ",".join(sorted(reasons(ed) - {"ocr_origin"})) or "-"
        lines.append(f"{name:34} {f_got:>4}/{f_all:<4} {r_got:>4}/{r_all:<4} {r_good:>7}  {flags}")
    for name in ("statement_us", "statement_in"):
        ed = run(name, form="scan", tmp=tmp_path)
        f_got, f_all, r_got, r_all, r_good = score(name, ed)
        lines.append(f"{name + ' (scan)':34} {f_got:>4}/{f_all:<4} {r_got:>4}/{r_all:<4} {r_good:>7}  "
                     f"{','.join(sorted(reasons(ed))) or '-'}")
        assert "ocr_origin" in reasons(ed) or not (ed.get("extracted_fields") or {})
    with capsys.disabled():
        print("\n" + "\n".join(lines))
