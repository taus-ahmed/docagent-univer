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


# ── Item 4: group headers across pages ───────────────────────────────────────

class TestGroupHeadersAcrossPages:
    """Group header at bottom of page 1 (no rows on page 1) → its rows are on
    page 2.  A second group starts on page 2 and its rows span into page 3.
    Both groups must be attached to every row that belongs to them, regardless
    of which page the group header was printed on.

    Uses _place_table directly with prev_tables to simulate the cross-page flow.
    """

    # Columns: ID | Date | Amount
    _COLS = [{"x0": 0,   "x1": 100, "align": "left"},
             {"x0": 110, "x1": 220, "align": "left"},
             {"x0": 230, "x1": 320, "align": "right"}]

    def _base_region(self, line_ids, group_header_line_ids):
        return {"id": "r1", "kind": "table",
                "line_ids": list(line_ids),
                "header_line_ids": [],
                "group_header_line_ids": list(group_header_line_ids),
                "columns": self._COLS,
                "labels": ["ID", "Date", "Amount"]}

    def _row_line(self, lid, top):
        """A data row line with an amount and a date."""
        ws = [_word(f"{lid}a", "REF01",     0,   80, top, top+12),
              _word(f"{lid}b", "04/01/2026", 110, 220, top, top+12),
              _word(f"{lid}c", "100.00",    240, 320, top, top+12)]
        ln = _line(lid, [f"{lid}a", f"{lid}b", f"{lid}c"], 0, 320, top, top+12,
                   text="REF01 04/01/2026 100.00")
        ln["date"] = True
        ln["n_amounts"] = 1
        return ws, ln

    def _group_line(self, lid, text, top):
        w = _word(lid + "_w", text, 0, 200, top, top+12)
        ln = _line(lid, [lid + "_w"], 0, 200, top, top+12, text=text)
        return [w], ln

    def _run_page(self, page_no, words, lines, region, prev_tables):
        """Call _place_table as place_page would, return rows and updated prev_tables."""
        import structure_engine as S
        page = _page(words, lines)
        page["page"] = page_no
        page["_by_id"] = {w["id"]: w for w in page["words"]}
        S._place_table(region, page, lines, row0=0, order={}, body={},
                       prev_tables=prev_tables)
        # simulate what place_page does after _place_table:
        prev_tables.append({
            "columns": region.get("_placed_columns") or region.get("columns"),
            "labels": region.get("_labels"),
            "column_groups": region.get("column_groups", 1),
            "page": page_no,
            "last_group": region.get("_last_group"),
            "last_on_page": True,
        })
        return region.get("_rows", [])

    def test_group_header_bottom_page1_rows_on_page2(self):
        """Group VENDOR_A header at bottom of page 1 with no rows.
        VENDOR_A's data rows on page 2 must carry _group = VENDOR_A."""
        # Page 1: VENDOR_A group header only, no rows
        gws, gln = self._group_line("pg1_ga", "VENDOR_A_11111", 50)
        p1_region = self._base_region(["pg1_ga"], ["pg1_ga"])
        pt = []
        rows_p1 = self._run_page(1, gws, [gln], p1_region, pt)

        # Page 2: continuation with 2 data rows for VENDOR_A
        rws1, rln1 = self._row_line("pg2_r1", 10)
        rws2, rln2 = self._row_line("pg2_r2", 25)
        p2_region = self._base_region(["pg2_r1", "pg2_r2"], [])
        p2_region["continued"] = True
        rows_p2 = self._run_page(2, rws1 + rws2, [rln1, rln2], p2_region, pt)

        # Both rows on page 2 must have _group pointing to VENDOR_A
        groups_on_p2 = [r.get("_group") for r in rows_p2 if any(isinstance(k, int) for k in r)]
        assert all(g is not None for g in groups_on_p2), (
            f"all data rows on page 2 must inherit VENDOR_A group; rows={rows_p2}")
        texts = [" ".join(w["text"] for w in list(g[0]) + list(g[1]))
                 for g in groups_on_p2 if g]
        assert any("VENDOR_A" in t for t in texts), (
            f"group text must contain VENDOR_A; groups_on_p2={groups_on_p2}")

    def test_group_rows_spanning_page2_to_page3(self):
        """VENDOR_B starts on page 2 (after VENDOR_A data rows) and has rows on
        both page 2 and page 3.  Page 3 rows must still carry VENDOR_B's group."""
        pt = []

        # Page 1: VENDOR_A header only (trailing, no rows)
        gws_a, gln_a = self._group_line("p1_ga", "VENDOR_A_11111", 50)
        p1_reg = self._base_region(["p1_ga"], ["p1_ga"])
        self._run_page(1, gws_a, [gln_a], p1_reg, pt)

        # Page 2: 2 VENDOR_A rows, then VENDOR_B header + 1 VENDOR_B row
        rws1, rln1 = self._row_line("p2_r1", 10)
        rws2, rln2 = self._row_line("p2_r2", 25)
        gws_b, gln_b = self._group_line("p2_gb", "VENDOR_B_22222", 42)
        rws3, rln3 = self._row_line("p2_r3", 55)
        # Note: p2_r1, p2_r2 inherit VENDOR_A; p2_r3 is under VENDOR_B
        p2_reg = self._base_region(
            ["p2_r1", "p2_r2", "p2_gb", "p2_r3"],
            ["p2_gb"])
        p2_reg["continued"] = True
        rows_p2 = self._run_page(2, rws1 + rws2 + gws_b + rws3,
                                 [rln1, rln2, gln_b, rln3], p2_reg, pt)

        # Page 3: continuation — 2 more rows for VENDOR_B
        rws4, rln4 = self._row_line("p3_r4", 10)
        rws5, rln5 = self._row_line("p3_r5", 25)
        p3_reg = self._base_region(["p3_r4", "p3_r5"], [])
        p3_reg["continued"] = True
        rows_p3 = self._run_page(3, rws4 + rws5, [rln4, rln5], p3_reg, pt)

        # Page 3 rows must carry VENDOR_B
        data_rows_p3 = [r for r in rows_p3 if any(isinstance(k, int) for k in r)]
        assert len(data_rows_p3) == 2, f"expected 2 data rows on page 3, got {rows_p3}"
        groups_p3 = [r.get("_group") for r in data_rows_p3]
        assert all(g is not None for g in groups_p3), (
            f"page 3 rows must inherit VENDOR_B group; rows={rows_p3}")
        texts = [" ".join(w["text"] for w in list(g[0]) + list(g[1]))
                 for g in groups_p3 if g]
        assert any("VENDOR_B" in t for t in texts), (
            f"page 3 group text must contain VENDOR_B; got={texts}")

    def test_s4a_does_not_fire_when_group_had_rows(self):
        """When a group header is followed by data rows on the SAME page, T3
        S4a must NOT emit a spurious section row for it."""
        # Page: VENDOR_A header + 2 rows + VENDOR_B header + 2 rows
        gws_a, gln_a = self._group_line("ga", "VENDOR_A", 10)
        rws1, rln1 = self._row_line("r1", 25)
        rws2, rln2 = self._row_line("r2", 40)
        gws_b, gln_b = self._group_line("gb", "VENDOR_B", 55)
        rws3, rln3 = self._row_line("r3", 70)
        rws4, rln4 = self._row_line("r4", 85)
        for ln in (rln1, rln2, rln3, rln4):
            ln["date"] = True
            ln["n_amounts"] = 1
        reg = self._base_region(["ga","r1","r2","gb","r3","r4"], ["ga","gb"])
        import structure_engine as S
        page = _page(gws_a + rws1 + rws2 + gws_b + rws3 + rws4,
                     [gln_a, rln1, rln2, gln_b, rln3, rln4])
        page["page"] = 1
        page["_by_id"] = {w["id"]: w for w in page["words"]}
        S._place_table(reg, page, page["lines"], row0=0, order={}, body={},
                       prev_tables=[])
        rows = reg.get("_rows", [])
        # Exactly 4 data rows, no spurious section row for VENDOR_B
        data_rows = [r for r in rows if any(isinstance(k, int) for k in r)]
        section_rows = [r for r in rows if r.get("_section") and not any(isinstance(k, int) for k in r)]
        assert len(data_rows) == 4, f"expected 4 data rows, got {len(data_rows)}: {rows}"
        assert len(section_rows) == 0, (
            f"no spurious section rows when groups had rows; got {section_rows}")
