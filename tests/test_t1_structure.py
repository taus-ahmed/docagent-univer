"""Run T1, Stage 3: the structure engine. Synthetic pages, no model (every
model answer is scripted)."""
from __future__ import annotations

import copy
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tests.harness import bootstrap as bs  # noqa: E402

bs.bootstrap()

import perception as P  # noqa: E402
import structure_engine as S  # noqa: E402
import structure_geometry as G  # noqa: E402
from tests import t1_pdf  # noqa: E402


def _right(x_right, y, text, size=10):
    """Text whose RIGHT edge is at x_right (Helvetica digits ~0.556 em)."""
    return (x_right - 0.556 * size * len(text), y, text)


def statement(n=6, y0=634, heading=True, start_bal=1000.0, side=False, note=True):
    items = [{"x": 200, "y": 750, "text": "Monthly Statement", "size": 16},
             (44, 690, "Statement Date: July 31, 2026"), (380, 690, "Account Number: 0025")]
    if heading:
        items += [(44, 650, "Date"), (110, 650, "Description"), (310, 650, "Debits"),
                  (380, 650, "Credits"), (450, 650, "Balance")]
    y, bal = y0, start_bal
    for i in range(n):
        d = (i + 1) * 10.0
        bal -= d
        items += [(44, y, f"07/{i + 13:02d}/2026"), (110, y, f"Card purchase {i}"),
                  _right(345, y, f"{d:.2f}"), _right(490, y, f"{bal:,.2f}")]
        y -= 14
    if note:
        items.append((44, y - 30, "This statement is provided for your records only and "
                                  "should be kept in a safe place."))
    if side:
        for k in range(8):
            items.append((540, 700 - 20 * k, f"Tip {k}"))
    return items


def _doc(tmp_path, pages, name="d.pdf"):
    return P.read_document(t1_pdf.make(tmp_path / name, pages))


def _grid(cells):
    g = {}
    for c in cells:
        g[(c["row"], c["col"])] = c["value"]
    return g


def _row_of(cells, value):
    return next(c["row"] for c in cells if c["value"] == value)


def _vals(cells):
    return [c["value"] for c in cells]


# ── 3d fallback + 3e placement ──────────────────────────────────────────────

class TestCompactGrids:
    def test_values_sit_under_their_own_headers_in_compact_columns(self, tmp_path):
        lay = S.layout_document(_doc(tmp_path, [statement()]))
        cells = lay["pages"][0]
        g = _grid(cells)
        hr = _row_of(cells, "Date")
        assert [g.get((hr, c)) for c in range(5)] == \
            ["Date", "Description", "Debits", "Credits", "Balance"]
        first = hr + 1
        assert g[(first, 2)] == 10.0 and (first, 3) not in g and g[(first, 4)] == 990.0
        assert g[(first, 1)] == "Card purchase 0"
        # no column beyond the table's five, no letterhead far right
        assert max(c["col"] for c in cells) <= 4

    def test_label_and_value_adjacent_with_colon_kept(self, tmp_path):
        cells = S.layout_document(_doc(tmp_path, [statement()]))["pages"][0]
        g = _grid(cells)
        r = _row_of(cells, "Statement Date:")
        assert g[(r, 1)].year == 2026 and g[(r, 2)] == "Account Number:"
        assert g[(r, 3)] == "0025"                        # leading zeros kept, text

    def test_regions_stacked_one_blank_row_apart(self, tmp_path):
        lay = S.layout_document(_doc(tmp_path, [statement()]))
        rows = sorted({c["row"] for c in lay["pages"][0]})
        assert rows[0] == 0                               # the title
        anchors = list(lay["anchors"][1].values())
        assert anchors[0] == "A1" and all(a.startswith("A") for a in anchors)
        # each gap between regions is exactly one blank row
        gaps = [b - a for a, b in zip(rows, rows[1:]) if b - a > 1]
        assert gaps and all(g == 2 for g in gaps)

    def test_note_and_side_panel_excluded_with_reasons(self, tmp_path):
        lay = S.layout_document(_doc(tmp_path, [statement(side=True)]))
        vals = " ".join(str(v) for v in _vals(lay["pages"][0]))
        assert "safe place" not in vals and "Tip 3" not in vals
        reasons = {e["reason"] for e in lay["excluded"]}
        assert any("note" in r for r in reasons) and any("side panel" in r for r in reasons)

    def test_watermark_never_reaches_a_cell(self, tmp_path):
        items = statement() + [{"x": 150, "y": 400, "text": "DRAFT", "angle": 45,
                                "size": 70, "gray": 0.85}]
        lay = S.layout_document(_doc(tmp_path, [items]))
        assert "DRAFT" not in " ".join(str(v) for v in _vals(lay["pages"][0]))
        assert any("background" in e["reason"] for e in lay["excluded"])

    def test_header_once_for_a_table_over_two_pages_headers_on_page_1_only(self, tmp_path):
        p2 = [(44, 750 - 14 * i, f"07/{i + 20:02d}/2026") for i in range(4)]
        p2 = [x for i in range(4) for x in (
            (44, 750 - 14 * i, f"07/{i + 20:02d}/2026"), (110, 750 - 14 * i, f"Fee {i}"),
            _right(345, 750 - 14 * i, f"{i + 1}.00"), _right(490, 750 - 14 * i, f"{900 - i:,.2f}"))]
        lay = S.layout_document(_doc(tmp_path, [statement(note=False), p2]))
        allv = [v for page in lay["pages"] for v in _vals(page)]
        assert allv.count("Debits") == 1 and allv.count("Balance") == 1
        g2 = _grid(lay["pages"][1])
        row = min(r for (r, c) in g2)
        assert g2[(row, 2)] == 1.0 and g2[(row, 4)] == 900.0 and (row, 3) not in g2

    def test_trailing_minus_and_formula_like_text(self, tmp_path):
        items = [(44, 700, "Ref"), (200, 700, "Amount"),
                 (44, 686, "=SUM(A1)"), _right(240, 686, "26.08-"),
                 (44, 672, "+44 20 7946"), _right(240, 672, "10.00"),
                 (44, 658, "@home"), _right(240, 658, "5.00")]
        cells = S.layout_document(_doc(tmp_path, [items]))["pages"][0]
        by = {c["value"]: c for c in cells}
        assert by[-26.08]["number_format"] == "#,##0.00;#,##0.00-"
        for t in ("=SUM(A1)", "+44 20 7946", "@home"):
            assert by[t]["as_text"]
        # and the writer stores them as text
        import openpyxl
        from app.services.excel_organized import write_layout
        wb = openpyxl.Workbook()
        write_layout(wb.active, {"pages": [cells]})
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        ws = openpyxl.load_workbook(buf).active
        f = [c for row in ws.iter_rows() for c in row if c.value == "=SUM(A1)"][0]
        assert f.data_type == "s"

    def test_no_fill_colours(self, tmp_path):
        import openpyxl
        from app.services.excel_organized import write_layout
        lay = S.layout_document(_doc(tmp_path, [statement()]))
        wb = openpyxl.Workbook()
        write_layout(wb.active, lay)
        for row in wb.active.iter_rows():
            for c in row:
                assert c.fill is None or c.fill.fill_type in (None, "none")


class TestTables:
    def test_repeated_column_groups_are_one_table(self, tmp_path):
        items = []
        for g, x in enumerate((40, 230, 420)):
            items += [(x, 700, "Number"), (x + 55, 700, "Date"), (x + 120, 700, "Amount")]
            for i in range(3):
                y = 686 - 14 * i
                items += [(x, y, f"N{g}{i}"), (x + 55, y, f"07/1{i}/2026"),
                          _right(x + 160, y, f"{g * 10 + i}.00")]
        cells = S.layout_document(_doc(tmp_path, [items]))["pages"][0]
        g = _grid(cells)
        hr = _row_of(cells, "Number")
        assert [g.get((hr, c)) for c in range(4)] == ["Number", "Date", "Amount", None]
        numbers = [g[(r, 0)] for r in range(hr + 1, hr + 10)]
        assert numbers == ["N00", "N01", "N02", "N10", "N11", "N12", "N20", "N21", "N22"]

    def test_group_header_carried_onto_rows(self, tmp_path):
        items = [(44, 700, "Invoice"), (150, 700, "Date"), (300, 700, "Amount")]
        y = 686
        for gid, name in (("300055", "NORTH SUPPLY"), ("400777", "SOUTH TRADING")):
            items.append((44, y, f"{gid} {name}"))
            y -= 14
            for i in range(2):
                items += [(44, y, f"INV{gid[-2:]}{i}"), (150, y, "07/14/2026"),
                          _right(340, y, f"{i + 1}.00")]
                y -= 14
        cells = S.layout_document(_doc(tmp_path, [items]))["pages"][0]
        g = _grid(cells)
        hr = _row_of(cells, "Invoice")
        r1 = hr + 1
        assert g[(r1, 0)] == "300055" and g[(r1, 1)] == "NORTH SUPPLY"
        assert g[(r1, 2)] == "INV550"
        r3 = hr + 3
        assert g[(r3, 0)] == "400777" and g[(r3, 2)] == "INV770"

    def test_wrapped_description_joins_its_row(self, tmp_path):
        items = [(44, 700, "Date"), (110, 700, "Description"), (300, 700, "Amount"),
                 (44, 686, "07/14/2026"), (110, 686, "Wire transfer to"), _right(340, 686, "50.00"),
                 (110, 675, "account holder"),
                 (44, 661, "07/15/2026"), (110, 661, "Fee"), _right(340, 661, "1.00")]
        cells = S.layout_document(_doc(tmp_path, [items]))["pages"][0]
        g = _grid(cells)
        hr = _row_of(cells, "Date")
        assert g[(hr + 1, 1)] == "Wire transfer to account holder"
        assert g[(hr + 2, 1)] == "Fee"
        assert (hr + 3, 0) not in g

    def test_right_aligned_amounts_under_centred_headers(self, tmp_path):
        items = [(44, 700, "Item"), (190, 700, "Amount"), (300, 700, "Tax")]
        for i, (a, t) in enumerate((("1,234.50", "12.00"), ("9.99", "0.10"), ("120.00", "1.20"))):
            items += [(44, 686 - 14 * i, f"Line {i}"), _right(235, 686 - 14 * i, a),
                      _right(320, 686 - 14 * i, t)]
        cells = S.layout_document(_doc(tmp_path, [items]))["pages"][0]
        g = _grid(cells)
        hr = _row_of(cells, "Item")
        assert [g[(hr + i, 1)] for i in (1, 2, 3)] == [1234.5, 9.99, 120.0]
        assert [g[(hr + i, 2)] for i in (1, 2, 3)] == [12.0, 0.1, 1.2]


# ── 3a/3c validator, owner addition: geometry first ─────────────────────────

class TestValidator:
    def _page(self, tmp_path):
        return _doc(tmp_path, [statement()])["pages"][0]

    def test_fallback_plan_is_valid(self, tmp_path):
        page = self._page(tmp_path)
        assert S.validate(G.fallback_plan(page), page) == []

    def test_unknown_line_double_assignment_and_missing_lines(self, tmp_path):
        page = self._page(tmp_path)
        plan = G.fallback_plan(page)
        bad = copy.deepcopy(plan)
        bad["regions"][0]["line_ids"].append("L999")
        bad["regions"][1]["line_ids"].append(plan["regions"][0]["line_ids"][0])
        bad["regions"].pop()
        errs = " | ".join(S.validate(bad, page))
        assert "does not exist" in errs and "two regions" in errs and "not assigned" in errs

    def test_ignored_needs_a_reason(self, tmp_path):
        page = self._page(tmp_path)
        plan = G.fallback_plan(page)
        lid = plan["regions"][0]["line_ids"].pop()
        plan["ignored"].append({"line_id": lid, "reason": ""})
        assert any("no reason" in e for e in S.validate(plan, page))

    def test_a_boundary_the_geometry_does_not_support_is_rejected(self, tmp_path):
        page = self._page(tmp_path)
        plan = G.fallback_plan(page)
        t = next(r for r in plan["regions"] if r["kind"] == "table")
        desc = t["columns"][1]
        mid = (desc["x0"] + desc["x1"]) / 2      # cut the description in two
        t["columns"][1:2] = [{"x0": desc["x0"], "x1": mid - 1}, {"x0": mid + 1, "x1": desc["x1"]}]
        errs = S.validate(plan, page)
        assert any("no alley or right edge" in e for e in errs)

    def test_a_named_contradiction_is_accepted_and_flagged(self, tmp_path):
        page = self._page(tmp_path)
        plan = G.fallback_plan(page)
        t = next(r for r in plan["regions"] if r["kind"] == "table")
        desc = t["columns"][1]
        mid = (desc["x0"] + desc["x1"]) / 2
        t["columns"][1:2] = [{"x0": desc["x0"], "x1": mid - 1}, {"x0": mid + 1, "x1": desc["x1"]}]
        plan["contradictions"] = [{"region": t["id"], "x": mid, "why": "two fields share a box"}]
        plan["source"] = "model"
        assert S.validate(plan, page) == []
        perc = {"pages": [page]}
        lay = S.layout_document(perc, plans={page["page"]: plan})
        assert lay["plan_source"][page["page"]] == "model"
        assert any("departs from the geometry" in f for f in lay["flags"])

    def test_merging_adjacent_candidates_is_allowed(self, tmp_path):
        page = self._page(tmp_path)
        plan = G.fallback_plan(page)
        t = next(r for r in plan["regions"] if r["kind"] == "table")
        a, b = t["columns"][2], t["columns"][3]          # Debits + Credits merged
        t["columns"][2:4] = [{"x0": a["x0"], "x1": b["x1"]}]
        assert S.validate(plan, page) == []


# ── 3b request, retry, fallback, splitting ──────────────────────────────────

class TestRequest:
    def test_request_carries_numbered_lines_with_coordinates_and_the_proposal(self, tmp_path):
        page = _doc(tmp_path, [statement()])["pages"][0]
        prop = G.proposal(page)
        req = S.build_request(page, prop)
        first = page["lines"][0]
        assert f"{first['id']} [" in req and first["text"] in req
        assert "candidate columns" in req and "Do not invent a boundary" in req

    def test_valid_plan_used(self, tmp_path):
        page = _doc(tmp_path, [statement()])["pages"][0]
        good = G.fallback_plan(page)
        calls = []

        def ask(prompt, lids):
            calls.append(prompt)
            return {k: good[k] for k in ("regions", "ignored", "contradictions")}, None
        res = S.ask_plan(ask, page)
        assert res["source"] == "model" and len(calls) == 1 and not res["errors"]

    def test_invalid_plan_retried_once_with_errors_then_fallback(self, tmp_path):
        page = _doc(tmp_path, [statement()])["pages"][0]
        calls = []

        def ask(prompt, lids):
            calls.append(prompt)
            return {"regions": [{"id": "r1", "kind": "table", "line_ids": ["L404"]}]}, None
        res = S.ask_plan(ask, page)
        assert len(calls) == 2 and "PREVIOUS PLAN WAS INVALID" in calls[1]
        assert "L404" in calls[1]
        assert res["source"] == "fallback" and res["errors"]
        assert S.validate(res["plan"], page) == []

    def test_retry_that_fixes_the_plan_is_used(self, tmp_path):
        page = _doc(tmp_path, [statement()])["pages"][0]
        good = G.fallback_plan(page)
        n = {"i": 0}

        def ask(prompt, lids):
            n["i"] += 1
            if n["i"] == 1:
                return {"regions": []}, None
            return {k: good[k] for k in ("regions", "ignored", "contradictions")}, None
        assert S.ask_plan(ask, page)["source"] == "model"

    def test_a_long_page_is_planned_in_pieces_and_halved_on_max_tokens(self, tmp_path, monkeypatch):
        monkeypatch.setattr(S, "MAX_LINES_PER_CALL", 6)
        page = _doc(tmp_path, [statement(n=20)])["pages"][0]
        good = G.fallback_plan(page)
        sizes = []

        class R:
            error_kind = "max_tokens"
            attempts = []

        def ask(prompt, lids):
            sizes.append(len(lids))
            if len(lids) > 6:
                return None, R()
            want = set(lids)
            regs = [{**r, "line_ids": [i for i in r["line_ids"] if i in want],
                     "header_line_ids": [i for i in r.get("header_line_ids") or [] if i in want],
                     "group_header_line_ids": []}
                    for r in good["regions"]]
            regs = [r for r in regs if r["line_ids"]]
            return {"regions": regs,
                    "ignored": [i for i in good["ignored"] if i["line_id"] in want]}, None
        res = S.ask_plan(ask, page)
        assert all(n <= 6 for n in sizes) and len(sizes) >= len(page["lines"]) // 6


# ── 3f verification ─────────────────────────────────────────────────────────

class TestVerify:
    def test_every_kept_word_placed_once(self, tmp_path):
        lay = S.layout_document(_doc(tmp_path, [statement(side=True)]))
        assert not [f for f in lay["flags"] if "not placed" in f or "more than once" in f]

    def test_a_lost_word_is_named(self, tmp_path):
        perc = _doc(tmp_path, [statement()])
        page = perc["pages"][0]
        plan = G.fallback_plan(page)
        t = next(r for r in plan["regions"] if r["kind"] == "table")
        # a plan whose columns stop short of the Balance column
        t["columns"] = t["columns"][:3]
        placed = S.place_page(page, plan)
        # words still go to the nearest column: nothing lost, but the plan
        # disagrees with the geometry, which verification says
        flags = S.verify(page, {**plan, "source": "model"}, placed, G.fallback_plan(page))
        assert any("different columns" in f for f in flags)

    def test_running_balance_break_is_named(self, tmp_path):
        items = statement(note=False)
        # corrupt one balance
        for i, it in enumerate(items):
            if isinstance(it, tuple) and it[2] == "960.00" and False:
                pass
        items = [it for it in items if not (isinstance(it, tuple) and it[2] == "940.00")]
        items.append(_right(490, 634 - 14 * 2, "945.00"))
        lay = S.layout_document(_doc(tmp_path, [items]))
        assert any("does not follow" in f for f in lay["flags"])

    def test_correct_balance_raises_nothing(self, tmp_path):
        lay = S.layout_document(_doc(tmp_path, [statement(note=False)]))
        assert not [f for f in lay["flags"] if "does not follow" in f]


# ── 3g determinism and the cache ────────────────────────────────────────────

class TestDeterminism:
    def test_same_input_same_layout(self, tmp_path):
        a = S.layout_document(_doc(tmp_path, [statement()], "a.pdf"))
        b = S.layout_document(_doc(tmp_path, [statement()], "b.pdf"))
        strip = lambda lay: [[{k: v for k, v in c.items()} for c in p] for p in lay["pages"]]
        assert json.dumps(strip(a), default=str) == json.dumps(strip(b), default=str)

    def test_plans_cached_by_hash_model_prompt_and_stored_with_the_words(self, tmp_path):
        perc = _doc(tmp_path, [statement()])
        good = G.fallback_plan(perc["pages"][0])
        n = {"calls": 0}

        def ask_page(page):
            def ask(prompt, lids):
                n["calls"] += 1
                return {k: good[k] for k in ("regions", "ignored", "contradictions")}, None
            return ask
        cache = {}
        S.make_plans(perc, ask_page, "abc", "m1", cache)
        S.make_plans(perc, ask_page, "abc", "m1", cache)
        assert n["calls"] == 1
        stored = json.loads(json.dumps(P.unpack(P.pack(perc))))
        assert S.stored_plans(stored)[1]["regions"]
        assert stored["plans"]["1"]["prompt_version"] == S.PROMPT_VERSION
        S.make_plans(perc, ask_page, "abc", "m2", cache)      # another model: asked
        assert n["calls"] == 2
        assert S.plan_key("abc", "m1", 1) != S.plan_key("abc", "m2", 1)


class TestNotNote:
    """Lines that LOOK long but are content (found on the oregon invoice,
    Batch 4 job 150): never excluded as note text."""

    def test_side_by_side_blocks_and_label_lines_are_kept(self, tmp_path):
        items = [(44, 712, "5219 Northwind Way Suite 12 Building C Eastside"),
                 (330, 712, "Period From Date: 03/01/2026"),
                 (44, 698, "Remit Payment To: Lakeside Partners, PO Box 4410, Rivertown, "
                           "State 12345-6789 and copy the office of grants"),
                 (44, 660, "By signing this report I certify that the information above is "
                           "true and complete to the best of my knowledge.")]
        lay = S.layout_document(_doc(tmp_path, [items]))
        vals = " ".join(str(v) for v in _vals(lay["pages"][0]))
        assert "Period From Date:" in vals and "Remit Payment To:" in vals
        assert "Northwind Way" in vals
        assert "best of my knowledge" not in vals


class TestNoDataColumns:
    def test_a_table_whose_rows_give_no_columns_takes_its_headings(self, tmp_path):
        # found on two corpus documents: an IndexError on an empty column list
        page = _doc(tmp_path, [[(44, 712, "Code"), (200, 712, "Name"), (330, 712, "Note")]])["pages"][0]
        feats = {ln["id"]: G.features(page, ln) for ln in page["lines"]}
        reg = G._table_region("r1", page, page["lines"], [page["lines"][0]["id"]], [], feats)
        assert len(reg["columns"]) == 3 and reg["labels"] == ["Code", "Name", "Note"]
        assert G.header_labels([], []) == []
