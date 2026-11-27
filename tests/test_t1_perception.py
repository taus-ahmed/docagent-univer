"""Run T1, Stage 2: perception - words with boxes, normalisation, lines by
baseline, background suppression on two signals, widgets as words, and the
stored form of it all. Code only; no model."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import perception as P  # noqa: E402
from tests import t1_pdf  # noqa: E402


def _table(y0=700, n=5, x=60):
    rows = [(x, y0, "Date"), (x + 120, y0, "Description"), (x + 380, y0, "Amount")]
    for i in range(n):
        y = y0 - 16 * (i + 1)
        rows += [(x, y, f"07/0{i + 1}/2026"), (x + 120, y, f"Item {i + 1}"),
                 (x + 380, y, f"{(i + 1) * 10}.00")]
    return rows


def _texts(doc, page=0):
    return [w["text"] for w in doc["pages"][page]["words"]]


def _removed(doc, page=0):
    return {r["text"]: r["reasons"] for r in doc["pages"][page]["removed"]}


# ── 2a ───────────────────────────────────────────────────────────────────────

class TestWords:
    def test_box_font_size_colour_rotation(self, tmp_path):
        pdf = t1_pdf.make(tmp_path / "w.pdf", [[
            {"x": 60, "y": 700, "text": "Heading", "size": 14},
            {"x": 60, "y": 680, "text": "grey", "gray": 0.5},
            {"x": 20, "y": 400, "text": "SIDE", "angle": 90}]])
        doc = P.read_document(pdf)
        by = {w["text"]: w for w in doc["pages"][0]["words"]}
        assert by["Heading"]["size"] == 14 and by["Heading"]["x0"] == 60
        assert by["Heading"]["top"] < by["Heading"]["bottom"]
        assert by["grey"]["color"] == [0.5]
        assert by["SIDE"]["rotation"] == 90.0
        assert all(w["origin"] == "text" for w in by.values())

    def test_quality_good_text_page(self, tmp_path):
        doc = P.read_document(t1_pdf.make(tmp_path / "q.pdf", [_table()]))
        q = doc["pages"][0]["quality"]
        assert q["source"] == "text" and q["score"] >= 0.9

    def test_quality_garbled_page_goes_to_ocr(self, tmp_path):
        items = [(60, 700 - 14 * i, "(cid:12)(cid:7) (cid:44)") for i in range(10)]
        doc = P.read_document(t1_pdf.make(tmp_path / "g.pdf", [items]))
        assert doc["pages"][0]["quality"]["source"] == "ocr"

    def test_quality_empty_page_goes_to_ocr(self, tmp_path):
        doc = P.read_document(t1_pdf.make(tmp_path / "e.pdf", [[]]))
        assert doc["pages"][0]["quality"]["source"] == "ocr"


# ── 2b ───────────────────────────────────────────────────────────────────────

class TestNormalise:
    def test_dashes_spaces_ligatures_zero_width(self):
        assert P.normalise("a–b—c−d") == "a-b-c-d"
        assert P.normalise("a b c") == "a b c"
        assert P.normalise("ﬁnance ﬂow") == "finance flow"
        assert P.normalise("ab​c­d") == "abcd"

    def test_glued_and_split_tokens_share_a_key(self):
        assert P.loose_key("ACHDEBIT") == P.loose_key("ACH DEBIT") == P.loose_key("ACH-DEBIT")
        assert P.loose_find("ACH DEBIT", "07/01 ACHDEBIT 12.00") == "ACHDEBIT"
        assert P.loose_find("ACH DEBIT", "07/01 ACH-DEBIT 12.00") == "ACH-DEBIT"
        assert P.loose_find("ACH", "ACHDEBIT") is None        # too short to trust
        assert P.loose_find("CH DEBI", "ACH DEBIT") is None   # not at a boundary

    def test_trailing_minus_is_a_sign(self):
        assert P.trailing_minus("26.08-") and P.trailing_minus("$1,234.50-")
        assert not P.trailing_minus("26.08") and not P.trailing_minus("ABC-")

    def test_grounding_ignores_punctuation_between_words(self):
        import slot_extractor as S
        assert S.verify_span("ACH DEBIT", "ACH-DEBIT 12.00", 1, ["ACH-DEBIT 12.00"])[0]
        assert S.verify_span("ACH DEBIT", "ACH DEBIT 12.00", 1, ["ACH-DEBIT 12.00"])[0]
        assert S.verify_span("ACHDEBIT", "ACH DEBIT 12.00", 1, ["ACH DEBIT 12.00"])[0]
        # a different word is still not grounded
        assert not S.verify_span("ACH CREDIT", "ACH-DEBIT 12.00", 1, ["ACH-DEBIT 12.00"])[0]


# ── 2c ───────────────────────────────────────────────────────────────────────

class TestLines:
    def test_lines_by_baseline_with_tolerance(self, tmp_path):
        pdf = t1_pdf.make(tmp_path / "l.pdf", [[
            (60, 700, "Left"), (200, 700.8, "Right"), (60, 680, "Next")]])
        doc = P.read_document(pdf)
        texts = [ln["text"] for ln in doc["pages"][0]["lines"]]
        assert texts == ["Left Right", "Next"]

    def test_superscript_stays_on_its_line(self, tmp_path):
        pdf = t1_pdf.make(tmp_path / "s.pdf", [[
            {"x": 60, "y": 700, "text": "Total", "size": 10},
            {"x": 88, "y": 704, "text": "1", "size": 6},
            {"x": 120, "y": 700, "text": "10.00", "size": 10}]])
        doc = P.read_document(pdf)
        lines = doc["pages"][0]["lines"]
        assert len(lines) == 1 and lines[0]["text"] == "Total 1 10.00"
        sup = [w for w in doc["pages"][0]["words"] if w["text"] == "1"][0]
        assert sup.get("sup")

    def test_two_line_stacked_cell(self, tmp_path):
        pdf = t1_pdf.make(tmp_path / "st.pdf", [[
            (60, 700, "Tran"), (60, 691, "Date"), (60, 660, "Far below"),
            (60, 630, "Also apart"), (60, 600, "Last")]])
        doc = P.read_document(pdf)
        lines = doc["pages"][0]["lines"]
        pairs = P.stacked_cells(lines)
        assert (lines[0]["id"], lines[1]["id"]) in pairs
        assert (lines[1]["id"], lines[2]["id"]) not in pairs
        # ordinary single-spaced text is not stacked
        assert P.stacked_cells([{**lines[2], "id": "a"}, {**lines[3], "id": "b"}]) == []


# ── 2d ───────────────────────────────────────────────────────────────────────

class TestBackground:
    def _wm(self, text, gray=0.85, angle=45, size=60):
        return {"x": 150, "y": 350, "text": text, "angle": angle, "size": size,
                "gray": gray}

    def test_diagonal_watermarks_are_removed_with_reasons(self, tmp_path):
        for word in ("SAMPLE", "DRAFT", "CONFIDENTIAL"):
            pdf = t1_pdf.make(tmp_path / f"{word}.pdf", [_table() + [self._wm(word)]])
            doc = P.read_document(pdf)
            assert word not in _texts(doc), word
            reasons = _removed(doc)[word]
            assert len(reasons) >= 2 and "rotated_large" in reasons
            assert "07/01/2026" in _texts(doc) and "Amount" in _texts(doc)

    def test_one_signal_is_not_enough(self, tmp_path):
        # dark, diagonal, large, clear of the content: only rotated_large
        pdf = t1_pdf.make(tmp_path / "one.pdf", [
            _table(y0=750, n=2) + [{"x": 100, "y": 200, "text": "PAID", "angle": 30,
                                    "size": 40}]])
        doc = P.read_document(pdf)
        assert "PAID" in _texts(doc) and not doc["pages"][0]["removed"]

    def test_repeated_faint_mark_on_every_page(self, tmp_path):
        page = _table() + [{"x": 500, "y": 40, "text": "COPY", "gray": 0.9, "size": 9}]
        doc = P.read_document(t1_pdf.make(tmp_path / "rep.pdf", [page, page]))
        for pi in (0, 1):
            assert "COPY" not in _texts(doc, pi)
            assert set(_removed(doc, pi)["COPY"]) >= {"faint", "repeated"}

    def test_real_rotated_headers_and_side_text_are_kept(self, tmp_path):
        items = _table() + [
            {"x": 300, "y": 720, "text": "Quantity", "angle": 90},
            {"x": 330, "y": 720, "text": "Weight", "angle": 90},
            {"x": 15, "y": 300, "text": "Statement continued overleaf", "angle": 90},
            {"x": 595, "y": 300, "text": "Form 77-B Rev 2026", "angle": 270}]
        doc = P.read_document(t1_pdf.make(tmp_path / "keep.pdf", [items]))
        t = " ".join(_texts(doc))
        for kept in ("Quantity", "Weight", "Statement continued overleaf",
                     "Form 77-B Rev 2026"):
            assert kept in t, kept
        assert not doc["pages"][0]["removed"]

    def test_a_faint_word_in_a_table_row_is_kept(self, tmp_path):
        items = _table()
        items.append({"x": 60, "y": 500, "text": "07/09/2026", "gray": 0.9})
        items.append({"x": 440, "y": 500, "text": "99.00", "gray": 0.9})
        items.append({"x": 60, "y": 500, "text": "07/09/2026", "gray": 0.9})
        doc = P.read_document(t1_pdf.make(tmp_path / "row.pdf", [items]))
        assert "99.00" in _texts(doc)


# ── 2e ───────────────────────────────────────────────────────────────────────

class TestWidgets:
    def test_fillable_form_values_and_checkboxes_are_words(self):
        pdf = ROOT / "tests" / "fixtures" / "FORM-CT3-FILLABLE.pdf"
        if not pdf.is_file():
            import pytest
            pytest.skip("fillable form fixture missing")
        doc = P.read_document(pdf)
        ws = [w for p in doc["pages"] for w in p["words"] if w["origin"] == "widget"]
        assert any(w["checkbox"] and w["text"] == "[X]" for w in ws)
        assert any(w["checkbox"] and w["text"] == "[ ]" for w in ws)
        for w in ws:
            assert w["x0"] < w["x1"] and w["top"] < w["bottom"]


# ── 2f ───────────────────────────────────────────────────────────────────────

class TestStorage:
    def test_pack_round_trips_and_is_compact(self, tmp_path):
        import json
        doc = P.read_document(t1_pdf.make(tmp_path / "p.pdf", [_table(n=30)]))
        s = P.pack(doc)
        assert s.startswith("pz1:") and len(s) < len(json.dumps(doc)) / 2
        assert P.unpack(s) == json.loads(json.dumps(doc))
        assert P.unpack(None) is None and P.unpack("pz1:garbage") is None


class TestGroundingBatch4:
    """Run T1, re-measured on the owner's Batch 4 carson exports (jobs 142,
    144): the two shapes left Low after Run T, with invented text."""

    def test_description_wrapped_past_its_rows_figures(self):
        import slot_extractor as S
        rec = "07/01/2026 RIVER GOODS WIREOUT SETTLEMENT STORE $21.70 $1,308.47\nNBR 4471"
        quote = rec.splitlines()[0]
        assert S.verify_span("RIVER GOODS WIRE OUT SETTLEMENT STORE NBR 4471", quote, 1,
                             [rec], record=rec)[0]
        # a WORD is never skipped: only the row's own figures
        assert not S.verify_span("RIVER GOODS SETTLEMENT NBR 4471", quote, 1, [rec],
                                 record=rec)[0]

    def test_trailing_minus_printed_as_its_own_token(self):
        import slot_extractor as S
        line = "07/22/2026 26.08 - 13.17 - 0.00 0.00"
        assert S.verify_span("-26.08", line, 1, [line])[0]
        assert S.verify_span("26.08", line, 1, [line])[0]          # unchanged
        assert not S.verify_span("-0.50", line, 1, [line])[0]


class TestDoubleStruck:
    def test_text_drawn_twice_in_place_is_one_word(self, tmp_path):
        items = [(60, 700, "99812"), (60, 700, "99812"), (160, 700, "Total")]
        doc = P.read_document(t1_pdf.make(tmp_path / "d.pdf", [items]))
        assert [ln["text"] for ln in doc["pages"][0]["lines"]] == ["99812 Total"]
