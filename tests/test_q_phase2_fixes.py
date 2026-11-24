"""Run Q Phase 2 — the three largest engine causes found by replaying the real
model answers (docs/RUN_Q_PHASE2_FINDINGS.md). Each unit test uses values and
geometry taken from the real replayed jobs. Each `_real` test replays the
stored answer and skips when local_docs/raw is absent."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))


def _replay(job_id):
    import replay_raw
    if not replay_raw.has_raw(job_id):
        pytest.skip(f"local_docs/raw/{job_id} not present")
    rep = replay_raw.replay_job(job_id)
    if not rep["docs"]:
        pytest.skip(f"job {job_id}: {rep['skipped']}")
    return rep


def _reasons(rep):
    out = []
    for _m, ed, _x in rep["docs"]:
        for f in ed["validation"]["flagged_fields"]:
            out.append((str(f.get("ref")), str(f.get("value")), str(f.get("reason"))))
    return out


# ── cause 1: a long identifier is not a phone number ─────────────────────────

class TestLongIdentifierIsNotAPhone:
    @pytest.mark.parametrize("value,label", [
        ("702000000803", "Batch"),                 # job 73, 12 digits
        ("08632520260515", "INVOICE"),             # job 72, 14 digits
        ("980104801-062326", "INVOICE"),           # job 72
    ])
    def test_one_datum(self, value, label):
        from slot_extractor import _single_datum
        assert _single_datum(value, label)

    @pytest.mark.parametrize("value", [
        "Robert Chen 555-123-4567",
        "Robert Chen (800) 544-5555",
        "Robert Chen 8005445555",
    ])
    def test_a_real_phone_beside_a_name_still_fails(self, value):
        from slot_extractor import _single_datum
        assert not _single_datum(value, "Contact Name")

    def test_real_job_73_batch_numbers(self):
        rep = _replay(73)
        bad = [r for r in _reasons(rep) if "more than one piece" in r[2]
               and r[0].startswith("SUMMARY BY BATCH")]
        assert bad == []


# ── cause 2: a repeated value's later copy, and a heading with no banded
#    neighbour (real coordinates from the replays of jobs 73 and 72) ─────────

def _ln(*ws):
    return [{"text": t, "x0": a, "x1": b, "top": 0.0, "bottom": 8.0} for t, a, b in ws]


class TestRepeatedValuePlacement:
    def test_job_73_fees_zero_after_two_other_zeros(self):
        from text_layer import check_placement
        row = {"Date Submitted": "04/30/18", "Submitted Amount": "$795.80",
               "Chargebacks/Reversals": "0.00", "Adjustments": "0.00", "Fees": "0.00",
               "Amount Processed": "$795.80"}
        cols = [{"key": k, "header": k} for k in row]
        line = _ln(("04/30/18", 58.5, 94.4), ("$795.80", 190.6, 221.6), ("0.00", 291.2, 308.0),
                   ("0.00", 369.9, 386.7), ("0.00", 439.9, 456.8), ("$795.80", 523.4, 554.4))
        bands = {"Date Submitted": (58.5, 124.8), "Amount Processed": (471.0, 550.6),
                 "Adjustments": (325.9, 379.3), "Fees": (417.1, 436.8)}
        assert check_placement(row, cols, line, bands) == []

    def test_job_72_po_equal_to_invoice(self):
        from text_layer import check_placement
        row = {"INVOICE": "26003220", "P.O.": "26003220", "INV DATE": "04/24/2026"}
        cols = [{"key": k, "header": k} for k in row]
        line = _ln(("26003220", 36.0, 69.7), ("26003220", 124.6, 158.3),
                   ("04/24/2026", 162.5, 204.7))
        bands = {"INVOICE": (36.0, 65.5), "P.O.": (95.0, 111.9), "INV DATE": (162.5, 196.3)}
        assert check_placement(row, cols, line, bands) == []

    def test_a_value_really_under_the_neighbour_still_fails(self):
        from text_layer import check_placement
        row = {"INVOICE": "26003220", "P.O.": "26003220"}
        cols = [{"key": k, "header": k} for k in row]
        line = _ln(("26003220", 36.0, 69.7))           # one copy only, under INVOICE
        bands = {"INVOICE": (36.0, 65.5), "P.O.": (95.0, 111.9), "INV DATE": (162.5, 196.3)}
        assert [k for k, _w in check_placement(row, cols, line, bands)] == ["P.O."]

    def test_job_72_unprinted_first_heading_bounded_by_the_printed_line(self):
        """The template's first column ('Invoice Number') is not printed, so
        P.O. has no banded left neighbour - the heading line's own INVOICE
        word bounds it."""
        from text_layer import check_placement, column_bands
        head = _ln(("INVOICE", 36.0, 65.5), ("P.O.", 95.0, 111.9), ("INV", 162.5, 175.2),
                   ("DATE", 179.4, 196.3), ("CHECK", 246.9, 268.0), ("RUN", 272.2, 284.8))
        bands = column_bands([head], ["Invoice Number", "P.O.", "INV DATE (Header)", "CHECK RUN"])
        assert set(bands) == {"P.O.", "CHECK RUN"}
        row = {"Invoice Number": "26003221", "Vendor Name": "TrippKappel",
               "Invoice Date": "04/24/2026", "P.O.": "26003221"}
        cols = [{"key": k, "header": k} for k in row]
        line = _ln(("26003221TrippKappel", 36.0, 116.1), ("26003221", 124.6, 158.3),
                   ("04/24/2026", 162.5, 204.7), ("H062426", 246.9, 276.4))
        assert check_placement(row, cols, line, bands) == []
        # under the printed INVOICE heading it is still misplaced
        line2 = _ln(("26003221", 36.0, 69.7), ("04/24/2026", 162.5, 204.7))
        assert [k for k, _w in check_placement({"P.O.": "26003221"},
                                               [{"key": "P.O.", "header": "P.O."}],
                                               line2, bands)] == ["P.O."]

    @pytest.mark.parametrize("job", [72, 73])
    def test_real_replay_has_no_repeated_value_placement_flags(self, job):
        rep = _replay(job)
        bad = [r for r in _reasons(rep)
               if ("'P.O.'" in r[2] and job == 72) or ("not 'Fees'" in r[2] and job == 73)]
        assert bad == []


# ── cause 4: a value read from a picture on a native page ───────────────────

SRC = ROOT / "local_docs" / "DocAgent_testdocs"


def _src(rel):
    p = SRC / rel
    if not p.exists():
        pytest.skip(f"{rel} not in local_docs")
    return p


class TestPictureOnANativePage:
    def test_ou_stub_page_1_is_a_picture_with_no_text_layer(self):
        from text_layer import image_only_pages
        assert image_only_pages(_src("payslip/ou_check_stub.pdf")) == {1}

    @pytest.mark.parametrize("rel", ["bank_statement/carson_bank_6pg.pdf",
                                     "payslip/utah_paystub_1.pdf"])
    def test_a_page_whose_image_carries_its_text_layer_is_not(self, rel):
        """utah_paystub_1: an image covers the page and the text layer lies
        over it (190 words inside) - not a picture without text."""
        from text_layer import image_only_pages
        assert image_only_pages(_src(rel)) == set()

    def test_real_job_66_values_are_unverified_not_low(self):
        rep = _replay(66)
        ((_m, ed, _x),) = rep["docs"]
        prov = ed["field_provenance"]
        page1 = [r for r, p in prov.items() if p.get("page") == 1]
        assert page1
        cm = ed["validation"]["confidence_map"]
        low_grounding_only = [r for r in page1 if cm.get(r) == "low"
                              and prov[r].get("review_reasons") == ["grounding_failed"]]
        assert low_grounding_only == []
        assert any("image_only" in (prov[r].get("review_reasons") or []) for r in page1)
        # the payslip arithmetic check still makes its values Low
        assert any(cm.get(r) == "low" for r in page1)

    def test_real_job_66_row_cells_are_not_painted_low(self):
        """A row moved to unverified keeps no `_ungrounded` list: every reader
        (review screen, export) turns an `_ungrounded` cell Low."""
        from app.core.review import row_cell_status
        rep = _replay(66)
        ((_m, ed, _x),) = rep["docs"]
        rows = [r for k, v in ed.items() if k.endswith("_rows") and isinstance(v, list)
                for r in v if isinstance(r, dict) and "image_only" in (r.get("_review_reasons") or [])]
        assert rows
        statuses = {row_cell_status(ed, r, c)["status"] for r in rows
                    for c in r if not str(c).startswith("_") and str(r[c]).strip()}
        assert statuses and "low" not in statuses
