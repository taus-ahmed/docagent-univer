"""Safety invariants, checked across generated inputs rather than examples.

  (a) a value read off an OCR'd or pre-OCR'd page is never `high`
  (b) a failed check leaves its value exactly `low`, review_required, with a
      reason
  (c) `needs_review` is True whenever any value has review_required
  (d) records out = documents in the generator's manifest truth, or the
      difference is VISIBLE (a record flagged `possible_multiple_documents`;
      an empty file is one record that needs review) — nothing dropped or
      merged silently
  (e) validators never raise on missing, odd or hostile input

No hypothesis in the environment (and no new dependency), so inputs come from
a seeded random generator: every run sees the same cases, and a failure names
its seed.
"""
from __future__ import annotations

import random
from decimal import Decimal

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import validators as V  # noqa: E402
from app.core.confidence import HIGH, LOW  # noqa: E402

FAIL_REASONS = {"grounding_failed", "placement_failed", "content_check_failed",
                "checksum_failed", "amount_mismatch", "totals_mismatch",
                "balance_mismatch", "payslip_mismatch", "receipt_mismatch"}

HOSTILE = [None, "", " ", "\t\n", "0", "-0.00", "$", "()", "(((", "1e309", "NaN",
           "∞", "9" * 400, "-" + "9" * 60 + ".99", "١٢٣٫٤٥", "‏١٠٠٫٠٠‏",
           "٠٢١٠٠٠٠٢١", "²³", "02100002¹", "₂₁", "١٢/٠٨/٢٠٢٦", "12.00 CR",
           "1.234,56", "TBD", "$1,234.56", "(10.00)", "10..00", "1,23,456.00",
           "😀", "a" * 5000, "DROP TABLE", "⑆021000021⑆ 7743882201⑈ 001847",
           "two hundred sixty-seven and 25/100", "²/100", "dollars", 12.5, 0,
           -1, 10 ** 30, Decimal("1E+40"), ["x"], {"v": 1}]

LABELS = ["Subtotal", "Sales Tax", "Tip", "Discount", "Total", "Total Due",
          "Amount in Figures", "Amount in Words", "Routing Number",
          "Account Number", "Cheque Number", "Date", "Opening Balance",
          "Closing Balance", "Total Credits", "Total Debits", "Gross Pay",
          "Total Deductions", "Net Pay", "YTD Gross", "Payee", "MICR Line",
          "", None, "Σ", "مجموع", "合計"]

COLUMNS = ["Description", "Amount", "Debit", "Credit", "Balance", "Date",
           "Deduction", "Qty", "Unit Price", "Total", ""]


def _context(rng):
    fields = [{"ref": f"B{i + 2}", "row_label": rng.choice(LABELS),
               "row": i if rng.random() < 0.9 else None}
              for i in range(rng.randint(0, 12))]
    values = {f["ref"]: rng.choice(HOSTILE) for f in fields if rng.random() < 0.85}
    tables, rows, incomplete = [], {}, set()
    for t in range(rng.randint(0, 2)):
        name = rng.choice(["table", "lines", "transactions", "deductions"]) + str(t)
        cols = [{"key": c or f"c{j}", "header": c} for j, c in
                enumerate(rng.sample(COLUMNS, rng.randint(0, 5)))]
        tables.append({"name": name, "columns": cols})
        rows[name] = [{c["key"]: rng.choice(HOSTILE) for c in cols}
                      for _ in range(rng.randint(0, 6))]
        if rng.random() < 0.2:
            rows[name].append(rng.choice([None, "row", 3, {}]))
        if rng.random() < 0.2:
            incomplete.add(name)
    pages = [rng.choice(HOSTILE + ["⑆021000021⑆ 7743882201⑈ 001847\n⑆0260⑆"])
             for _ in range(rng.randint(0, 3))]
    return V.CheckContext(fields=fields, values=values, pages=pages, tables=tables,
                          rows=rows, incomplete=incomplete)


FAMILIES = sorted(V.FAMILY_ALIASES) + ["other", None]


@pytest.mark.parametrize("seed", range(40))
def test_e_validators_never_raise(seed):
    rng = random.Random(seed)
    for _ in range(25):
        ctx = _context(rng)
        for fam in FAMILIES:
            out = V.run_checks(fam, ctx)
            assert isinstance(out, list), (seed, fam)
            crashed = [r for r in out if r.needs_review and not r.slots
                       and any("could not run" in x for x in r.notes)]
            assert not crashed, (seed, fam, crashed[0].notes)
            for r in out:
                assert r.status in (V.PASS, V.FAIL, V.UNREADABLE), (seed, fam, r)
                # a result that names values must say why; one with no value
                # to sit on (a band with no readable transit) only reports
                assert r.status == V.PASS or r.reason or not r.slots, (seed, fam, r)


@pytest.mark.parametrize("value", HOSTILE)
def test_e_parsers_never_raise(value):
    from cheque_amounts import parse_numeric_amount, parse_words_amount
    from duplicates import identity
    from invoice_validators import money
    from micr import aba_is_valid
    money(value)
    aba_is_valid(value)
    parse_numeric_amount(value)
    parse_words_amount(value)
    identity({"extracted_fields": {"B2": value},
              "slot_map": {"fields": [{"ref": "B2", "row_label": "Routing Number"}]}})


def test_e_a_validator_that_raises_is_visible_not_fatal(monkeypatch):
    def boom(ctx):
        raise RuntimeError("bad input")
    monkeypatch.setitem(V.REGISTRY, "ledger", [boom])
    out = V.run_checks("ledger", V.CheckContext(fields=[], values={}, pages=[]))
    (r,) = [x for x in out if x.check == "boom"]
    assert r.status == V.UNREADABLE and r.needs_review
    assert "boom check could not run" in r.notes[0] and r.flags


# ── (b) (c) on generated documents: the invoice / receipt fixture, corrupted ──

def _invariants(ed, where):
    cmap = ed["validation"]["confidence_map"]
    owed = False
    for ref, p in ed["field_provenance"].items():
        rs = set(p.get("review_reasons") or [])
        if rs & FAIL_REASONS:
            assert cmap.get(ref) == LOW, (where, ref, rs, cmap.get(ref))
        if cmap.get(ref) == LOW and str(ed["extracted_fields"].get(ref) or "").strip():
            assert p.get("review_required") is True and rs, (where, ref, p)
        owed |= bool(p.get("review_required"))
    for key, rows in ed.items():
        if key.endswith("_rows") and isinstance(rows, list):
            for row in rows:
                rs = set(row.get("_review_reasons") or [])
                if rs & FAIL_REASONS:
                    assert row.get("_confidence") == LOW, (where, row)
                owed |= bool(row.get("_review_required"))
    if owed:
        assert ed["needs_review"] is True, where


CORRUPT = ["$999.99", "TBD", "", "$-1.00", "1.234,56", "$0.00", "(15.00)", "8.88%"]


@pytest.mark.parametrize("seed", range(12))
def test_b_c_a_failed_check_is_low_and_the_document_needs_review(tmp_path, seed):
    from tests.test_invoice_totals import _invoice, _run, _template
    rng = random.Random(1000 + seed)
    labels = ["Subtotal", "Shipping & Handling", "Sales Tax", "Discount", "Total Due"]
    good = ["$250.00", "$15.00", "$20.00", "($10.00)", "$275.00"]
    vals = [rng.choice(CORRUPT) if rng.random() < 0.35 else v for v in good]
    summary = [(lab, v) for lab, v in zip(labels, vals) if v]
    doc_type = rng.choice(["invoice", "receipt", "sales_invoice", "other"])
    template = _template(doc_type, [lab for lab, _ in summary])
    ed, _refs, _rows = _run(_invoice(tmp_path, summary), summary, template)
    _invariants(ed, (seed, doc_type, summary))


# ── (a) (c) (d) on the generated cheque scans ────────────────────────────────

from tests.test_multi_cheque import (HAS_TESSERACT, _records,  # noqa: E402,F401,F811
                                     variants)


@pytest.mark.skipif(not HAS_TESSERACT, reason="no tesseract binary")
def test_a_c_d_every_generated_scan(variants):  # noqa: F811 (the fixture)
    out_dir, manifest = variants
    for name, entry in sorted(manifest.items()):
        records = _records(variants, name)
        truth = entry.get("documents_in_reading_order") or []
        eds = [r.extracted_data for r in records if isinstance(r.extracted_data, dict)]
        assert len(eds) == len(records), (name, "a record with no result dict")
        for ed in eds:
            origins = {str(k): v for k, v in
                       ((ed.get("validation") or {}).get("page_origins") or {}).items()}
            for ref, p in (ed.get("field_provenance") or {}).items():
                page_origin = p.get("origin") or origins.get(str(p.get("page")))
                if page_origin in ("ocr", "pre_ocr"):
                    assert ed["validation"]["confidence_map"].get(ref) != HIGH, (name, ref)
            _invariants(ed, name)
        if not truth:
            assert len(records) == 1 and eds[0]["needs_review"] is True, name
        elif len(records) != len(truth):
            assert len(records) < len(truth), (name, len(records), len(truth))
            assert any((ed.get("validation") or {}).get("possible_multiple_documents")
                       and ed["needs_review"] for ed in eds), (
                name, f"{len(truth)} documents became {len(records)} records silently")
