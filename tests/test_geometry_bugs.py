"""Run T3, Stage 4: synthetic tests for geometry bugs:
(a) a trailing group header (last vendor in a list, no data rows following)
    must appear in the output — it was silently lost before T3 S4a;
(b) two invoice rows glued into one pdfplumber line must each appear as a
    separate row — they were merged before T3 S4b.
"""
import sys, os, statistics
import pytest

@pytest.fixture(autouse=True)
def _engine_path():
    backend = os.path.join(os.path.dirname(__file__), "..", "backend")
    engine  = os.path.join(backend, "engine")
    for p in (backend, engine):
        if p not in sys.path:
            sys.path.insert(0, p)


# ── helpers ──────────────────────────────────────────────────────────────────

def _word(wid, text, x0, x1, top, bottom, baseline=None, size=10.0):
    if baseline is None:
        baseline = bottom - 2
    return {"id": wid, "text": text, "x0": float(x0), "x1": float(x1),
            "top": float(top), "bottom": float(bottom),
            "baseline": float(baseline), "size": float(size)}


def _line(lid, word_ids, x0, x1, top, bottom, baseline=None, text=""):
    if baseline is None:
        baseline = bottom - 2
    return {"id": lid, "word_ids": list(word_ids),
            "x0": float(x0), "x1": float(x1),
            "top": float(top), "bottom": float(bottom),
            "baseline": float(baseline),
            "text": text,
            "date": False, "n_amounts": 0,
            "pair": False, "size": 10.0}


def _page(words, lines, width=612, height=792):
    return {"page": 1, "width": float(width), "height": float(height),
            "words": words, "lines": lines,
            "edges": {"h": [], "v": []}}


# ── Stage 4a: trailing group header ─────────────────────────────────────────

class TestTrailingGroupHeader:
    """The last vendor in a grouped table has no data rows following it on the
    page.  Before T3 S4a the group header was set in `group_cur` but never
    attached to a row, so it was silently lost."""

    def _run(self):
        import structure_engine as S
        import structure_geometry as G

        # Columns: Ref | Date | Amount
        cols = [{"x0": 0, "x1": 100, "align": "left"},
                {"x0": 110, "x1": 220, "align": "left"},
                {"x0": 230, "x1": 320, "align": "right"}]

        # Group header word (vendor A)
        w_ga = _word("w_ga", "VENDOR_A_12345", 0, 200, top=10, bottom=22)
        # Data row under vendor A
        w_ref = _word("w_ref",  "REF001",     0,   80, top=25, bottom=37)
        w_dat = _word("w_dat",  "04/01/2026", 110, 220, top=25, bottom=37)
        w_amt = _word("w_amt",  "1,000.00",   240, 320, top=25, bottom=37)
        # Group header word (vendor B — last vendor, no data rows follow)
        w_gb = _word("w_gb", "VENDOR_B_99999", 0, 200, top=42, bottom=54)

        ln_ga  = _line("lg_a", ["w_ga"],                 0,   200,  10,  22, text="VENDOR_A_12345")
        ln_row = _line("l_row", ["w_ref","w_dat","w_amt"], 0, 320,  25,  37, text="REF001 04/01/2026 1,000.00")
        ln_gb  = _line("lg_b", ["w_gb"],                 0,   200,  42,  54, text="VENDOR_B_99999")
        # Mark the group lines and the data row line manually
        ln_row["date"] = True
        ln_row["n_amounts"] = 1

        words = [w_ga, w_ref, w_dat, w_amt, w_gb]
        lines = [ln_ga, ln_row, ln_gb]
        page  = _page(words, lines)
        page["_by_id"] = {w["id"]: w for w in page["words"]}

        region = {
            "id": "r1", "kind": "table",
            "line_ids": ["lg_a", "l_row", "lg_b"],
            "header_line_ids": [],
            "group_header_line_ids": ["lg_a", "lg_b"],
            "columns": cols,
            "labels": ["Ref", "Date", "Amount"],
        }
        body = {}
        order = {}
        S._place_table(region, page, lines, row0=0,
                       order=order, body=body, prev_tables=[])
        # _place_table stores the processed rows on region["_rows"]
        return region.get("_rows", [])

    def test_trailing_group_header_emitted(self):
        rows = self._run()
        # vendor B should appear in the output as a section or standalone row.
        # _group is (gid_words, gname_words); gid is the identifier (first word).
        group_texts = []
        for row in rows:
            if row.get("_group"):
                gid, gname = row["_group"]
                all_ws = list(gid) + list(gname)
                group_texts.append(" ".join(w["text"] for w in all_ws))
        assert any("VENDOR_B" in t for t in group_texts), (
            f"trailing group header VENDOR_B_99999 must appear in output rows, "
            f"got rows={rows}, group_texts={group_texts}")

    def test_data_row_still_present(self):
        rows = self._run()
        # The data row under vendor A must also be present (it has column keys 0,1,2)
        data_rows = [r for r in rows if not r.get("_section") and
                     any(isinstance(k, int) for k in r)]
        assert len(data_rows) >= 1, (
            f"data row with column cells must be present in rows={rows}")


# ── Stage 4b: stacked rows ───────────────────────────────────────────────────

class TestStackedRows:
    """Two invoice rows that pdfplumber merged into one line because they were
    printed very close together.  _split_stacked_words must split them when
    each sub-cluster looks like a row line (has a date or an amount)."""

    def _make_stacked_line(self):
        """Two invoice rows at baselines 100 and 112 — gap=12 > 0.4*10=4."""
        import structure_engine as S

        # Row 1: baseline 100
        w1a = _word("w1a", "AJ1H23L",   0,  60,  90, 102, baseline=100)
        w1b = _word("w1b", "04/25/2026", 70, 180,  90, 102, baseline=100)
        w1c = _word("w1c", "122.95",    200, 260,  90, 102, baseline=100)
        # Row 2: baseline 112
        w2a = _word("w2a", "AJ1HY9H",   0,  60, 104, 116, baseline=112)
        w2b = _word("w2b", "04/25/2026", 70, 180, 104, 116, baseline=112)
        w2c = _word("w2c", "24.46",     200, 260, 104, 116, baseline=112)

        ws = [w1a, w1b, w1c, w2a, w2b, w2c]
        pitch = 12.0
        return S._split_stacked_words(ws, pitch), ws

    def test_split_into_two(self):
        splits, ws = self._make_stacked_line()
        assert len(splits) == 2, (
            f"two stacked row-line clusters must be split into 2, got {len(splits)}")

    def test_each_split_has_date_and_amount(self):
        import structure_engine as S
        import structure_geometry as G
        splits, _ = self._make_stacked_line()
        for i, sub_ws in enumerate(splits):
            text = " ".join(w["text"] for w in sub_ws)
            has_date   = G.has_date(text)
            has_amount = any(G.is_amount(w["text"]) for w in sub_ws)
            assert has_date or has_amount, (
                f"split {i} must look like a row line; text={text!r}")

    def test_no_split_when_single_baseline(self):
        """A normal single-row line must NOT be split."""
        import structure_engine as S
        ws = [
            _word("w1", "INV001",     0,  60, 100, 112, baseline=108),
            _word("w2", "04/01/2026", 70, 180, 100, 112, baseline=108),
            _word("w3", "500.00",    200, 260, 100, 112, baseline=108),
        ]
        splits = S._split_stacked_words(ws, pitch=12.0)
        assert len(splits) == 1, (
            f"single-baseline line must not be split; got {len(splits)} splits")

    def test_no_split_when_non_row_lines(self):
        """Two baselines but neither cluster has a date or amount: no split."""
        import structure_engine as S
        # label row over another label row: no dates/amounts
        ws = [
            _word("w1", "Vendor",   0, 60, 100, 112, baseline=108),
            _word("w2", "Name",    70, 120, 100, 112, baseline=108),
            _word("w3", "Address",  0, 80, 115, 127, baseline=123),
            _word("w4", "City",    90, 150, 115, 127, baseline=123),
        ]
        splits = S._split_stacked_words(ws, pitch=12.0)
        assert len(splits) == 1, (
            f"non-row-line clusters must not be split; got {len(splits)} splits")
