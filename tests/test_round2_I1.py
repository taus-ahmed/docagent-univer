"""
I1 — a band is bound to ONE region of the document, and says so when more
than one matched (docs/DocAgent_round2_report.md, runs 1-6, 11).

The suite passed at 781 while eight of twelve manual runs merged regions, so
the evidence here runs the round-2 documents themselves.

TWO MECHANISMS, found by reading the code rather than the symptom:

  BERKSHIRE (runs 1-3). `feb2225.pdf` is one document. The prompt asks for
  "one object per row present in the document" over both pages, and every row
  that came back was kept. The live answer recorded for this gate
  (tests/fixtures/round2_raw/run1_berkshire_B1.json) returned the page-1
  earnings table AND the page-2 operating-earnings table — 8 + 8 rows — for one
  band. Nothing was injected: the test replays what the model actually said.

  ENGIE (runs 4, 6, and I12). `SampleBill.pdf` was cut into two documents at
  page 4, because a keyword classifier read the meter/glossary page as a tax
  form. The second "document" was asked for the whole template, and the writer
  stacked it under a second copy of the template — heading row included. The
  evidence is the split and the writer, which are deterministic; the model is
  replaced by a stub that answers with the lines the report says were bound
  (the page-4 glossary into the charges table, the overprinted account number
  into the bill header) whenever those lines are in the prompt it is given.

Run against fe3385d (before the fix), every test in the first three classes
fails; see the gate report for the before/after.
"""
import json
import re

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from tests.harness import round2  # noqa: E402

ARTIFACT = "00000000112538645596"
GLOSSARY = ("Meter Constant - A fixed value which is used when converting "
            "meter readings to actual energy use.")


def _cells(ws):
    return [str(v) for row in ws.iter_rows(values_only=True)
            for v in row if v not in (None, "")]


# ══════════════════════════════════════════════════════════════════════════
# BERKSHIRE — the recorded live answer, replayed
# ══════════════════════════════════════════════════════════════════════════

class TestBerkshireTablesDoNotMerge:
    @pytest.fixture(scope="class")
    def run(self):
        results, grid, _log = round2.run("run1_berkshire_B1", mode="replay")
        return results, round2.export(results, grid)

    def test_the_model_really_returned_both_tables(self):
        """Not a tautology: the recorded answer carries rows from both pages,
        so a pass below is the pipeline refusing them, not the model never
        offering them."""
        rec = json.loads((round2.RAW_DIR / "run1_berkshire_B1.json")
                         .read_text(encoding="utf-8"))
        raw = json.loads(rec["responses"][0]["raw_llm_responses"][0])
        pages = [r["page"] for r in raw["tables"]["table"]]
        assert pages.count(1) == 8 and pages.count(2) == 8

    def test_one_document(self, run):
        results, _ws = run
        assert len(results) == 1

    def test_only_the_page_one_table_is_written(self, run):
        results, ws = run
        rows = results[0].extracted_data["table_rows"]
        assert len(rows) == 8
        text = " ".join(_cells(ws))
        for page_two in ("Insurance-underwriting", "BNSF",
                         "Non-controlled businesses"):
            assert page_two not in text

    def test_the_legitimately_repeated_row_survives(self, run):
        """Protected (report line 217): page 1 prints `Net earnings
        attributable to Berkshire shareholders` twice, identical values, and
        both rows come back."""
        results, _ws = run
        items = [r.get("Item", "") for r in
                 results[0].extracted_data["table_rows"]]
        assert sum("Net earnings attributable" in i for i in items) == 2

    def test_the_second_region_is_reported_with_its_pages(self, run):
        results, _ws = run
        v = results[0].extracted_data["validation"]
        assert v["regions"] == [{"table": "table", "pages": [1, 2],
                                 "kept_page": 1, "kept_rows": 8,
                                 "left_out": 8}]
        assert v["unbound_row_count"] == 8
        warn = [f for f in v["flagged_fields"] if f["ref"] == "table[regions]"]
        assert len(warn) == 1
        assert "2 regions" in warn[0]["reason"]
        assert "pages 1, 2" in warn[0]["reason"]
        assert results[0].extracted_data["needs_review"] is True

    def test_every_row_left_out_is_visible_with_its_content(self, run):
        results, _ws = run
        out = [f for f in results[0].extracted_data["validation"]
               ["flagged_fields"] if f["ref"] == "table[not bound]"]
        assert len(out) == 8
        assert any("BNSF" in f["value"] for f in out)

    def test_the_heading_row_is_written_once(self, run):
        _results, ws = run
        assert _cells(ws).count("Full Year 2024") == 1


# ══════════════════════════════════════════════════════════════════════════
# ENGIE — the split and the writer
# ══════════════════════════════════════════════════════════════════════════

class _ReportStub:
    """Answers with what round 2 observed being bound, when it is on offer.

    Fields: `Bill Account Number` gets the page-1 value if the prompt has page
    1, else the overprinted page-4 string (runs 4 and 9 both produced it).
    Table: every charge line on page 3 that the prompt carries, plus the page-4
    glossary line (run 6). The stub reads only the PROMPT, so it can only
    return what the pipeline chose to show it.
    """

    CHARGES = ["Oncor Customer Charge $2.05", "Metering Charge $6.07"]

    def extract(self, text="", image_b64="", prompt="", **_kw):
        from connectors.groq_client import LLMResponse
        fields = {}
        for sid, label in re.findall(r'^\s+(F\d+): .*"([^"]+)"$', prompt, re.M):
            if label != "Bill Account Number":
                continue
            if "BILL ACCOUNT NUMBER: 0000123456" in prompt:
                fields[sid] = {"value": "0000123456", "page": 1,
                               "source": "BILL ACCOUNT NUMBER: 0000123456 Amount DUE DATE"}
            elif ARTIFACT in prompt:
                fields[sid] = {"value": ARTIFACT, "source": ARTIFACT, "page": 1}
        rows = []
        pages = re.split(r"^--- page (\d+) ---$", prompt, flags=re.M)
        for n, body in zip(pages[1::2], pages[2::2]):
            for line in body.splitlines():
                if any(c in line for c in self.CHARGES):
                    label, amount = line.rsplit(" ", 1)
                    rows.append({"cells": {"Charge Description": label,
                                           "Amount": amount},
                                 "source": line, "page": int(n)})
                if line.strip() == GLOSSARY:
                    rows.append({"cells": {"Charge Description": line,
                                           "Amount": ""},
                                 "source": line, "page": int(n)})
        tables = {}
        if "TABLE \"Charge Description\"" in prompt:
            tables["Charge Description"] = rows
        payload = {"fields": fields, "tables": tables}
        return LLMResponse(raw_text=json.dumps(payload), parsed_json=payload,
                           model_used="report-stub", tokens_used=0,
                           latency_ms=0, success=True, error="")

    def classify(self, **_kw):  # pragma: no cover - not reached
        raise AssertionError("no classification call expected")


class TestEngieIsNotSplitAtItsGlossaryPage:
    def test_the_split_decision(self, pdf_dir):
        import pdfplumber
        from doc_boundaries import find_starts
        from text_layer import read_page
        with pdfplumber.open(pdf_dir / "round2" / "SampleBill.pdf") as pdf:
            pages = [read_page(p)[0] for p in pdf.pages]
        assert find_starts(pages)[0] == [0]

    def test_page_four_still_reads_as_another_type(self, pdf_dir):
        """Why it used to split — and why a keyword type change is not
        allowed to decide on its own."""
        import pdfplumber
        from doc_boundaries import _doc_type
        with pdfplumber.open(pdf_dir / "round2" / "SampleBill.pdf") as pdf:
            types = [_doc_type(p.extract_text() or "") for p in pdf.pages]
        assert types[0] == "sales_invoice" and types[3] == "tax_form"


class TestEngieChargesDoNotTakeTheGlossary:
    """Run 6: the page-4 glossary appended to the page-3 charges table, under
    a second `Charge Description | Amount` heading."""

    @pytest.fixture(scope="class")
    def run(self):
        results, grid, _log = round2.run("run6_engie_E3",
                                         orchestrator_llm=_ReportStub())
        return results, round2.export(results, grid)

    def test_one_document(self, run):
        results, _ws = run
        assert len(results) == 1

    def test_the_glossary_is_not_in_the_sheet(self, run):
        _results, ws = run
        assert not any("Meter Constant" in c for c in _cells(ws))

    def test_the_template_heading_is_not_re_emitted_as_data(self, run):
        """Runs 6 and 11, manifestation (b)."""
        _results, ws = run
        cells = _cells(ws)
        assert cells.count("Charge Description") == 1
        assert cells.count("Amount") == 1

    def test_the_charges_are_written(self, run):
        results, _ws = run
        rows = results[0].extracted_data["Charge Description_rows"]
        assert [r["Amount"] for r in rows] == ["$2.05", "$6.07"]

    def test_the_second_region_is_reported(self, run):
        results, _ws = run
        v = results[0].extracted_data["validation"]
        assert [(r["pages"], r["kept_page"], r["left_out"])
                for r in v["regions"]] == [([3, 4], 3, 1)]


class TestEngieHeaderIsNotRepeatedFromPageFour:
    """Run 4: the page-4 header block appended below the page-1 one."""

    @pytest.fixture(scope="class")
    def run(self):
        results, grid, _log = round2.run("run4_engie_E1",
                                         orchestrator_llm=_ReportStub())
        return results, round2.export(results, grid)

    def test_one_document(self, run):
        results, _ws = run
        assert len(results) == 1

    def test_the_header_block_is_written_once(self, run):
        _results, ws = run
        cells = _cells(ws)
        assert cells.count("Bill Account Number") == 1
        assert cells.count("Billing Period") == 1

    def test_the_overprinted_page_four_number_is_not_a_second_answer(self, run):
        _results, ws = run
        assert ARTIFACT not in _cells(ws)


# ══════════════════════════════════════════════════════════════════════════
# PROTECTED — run 8's four quadrants
# ══════════════════════════════════════════════════════════════════════════

class TestFourQuadrantsOnOnePageAreUntouched:
    """Run 8 bound H25B's K / L / M / N summaries to four quadrants correctly
    (report line 213). Region selection only ever leaves out rows on a page
    OTHER than the one the answer began on, so it cannot remove a row from a
    table that lives on one page. This pins that the four sections really are
    on one page of the real file, which is what makes the argument hold."""

    @pytest.fixture(scope="class")
    def lines(self, pdf_dir):
        import pdfplumber
        from text_layer import flatten_pages, read_page
        with pdfplumber.open(
                pdf_dir / "201403_cfpb_closing-disclosure_cover-H25B.pdf") as pdf:
            return flatten_pages([read_page(p)[1] for p in pdf.pages])

    def test_all_four_sections_share_a_page(self, lines):
        from text_layer import line_page
        heads = ("K. Due from Borrower at Closing",
                 "L. Paid Already by or on Behalf of Borrower at Closing",
                 "M. Due to Seller at Closing",
                 "N. Due from Seller at Closing")
        pages = set()
        for h in heads:
            hit = [line_page(ln) for ln in lines
                   if h.casefold() in " ".join(w["text"] for w in ln).casefold()]
            assert hit, h
            pages.update(hit)
        assert len(pages) == 1, pages

    def test_rows_from_one_page_are_never_selected_against(self, lines):
        from slot_extractor import select_region
        from text_layer import line_page, source_occurrences
        page = {line_page(ln) for ln in lines
                if "due from borrower at closing" in
                " ".join(w["text"] for w in ln).casefold()}.pop()
        on_page = [" ".join(w["text"] for w in ln) for ln in lines
                   if line_page(ln) == page][:30]
        located = [({"x": s}, s, 1, s.casefold(), source_occurrences(lines, s))
                   for s in on_page]
        kept, region = select_region(located, lines, [])
        assert region is None and len(kept) == len(located)


# ══════════════════════════════════════════════════════════════════════════
# select_region, directly
# ══════════════════════════════════════════════════════════════════════════

def _line(text, page=None):
    words = [{"text": t, "x0": 0, "x1": 1, "top": 0} for t in text.split()]
    if page is not None:
        for w in words:
            w["page"] = page
    return words


class TestSelectRegion:
    def _located(self, lines, sources, model_page=1):
        from text_layer import source_occurrences
        return [({"a": s}, s, model_page, s, source_occurrences(lines, s))
                for s in sources]

    def test_no_geometry_no_verdict(self):
        from slot_extractor import select_region
        lines = [_line("a 1"), _line("b 2")]
        loc = self._located(lines, ["a 1", "b 2"])
        assert select_region(loc, lines, []) == (loc, None)

    def test_the_page_the_answer_begins_on_is_kept(self):
        from slot_extractor import select_region
        lines = [_line("a 1", 1), _line("b 2", 2), _line("c 3", 2)]
        kept, region = select_region(
            self._located(lines, ["b 2", "a 1", "c 3"]), lines, [])
        assert [s for _c, s, *_ in kept] == ["b 2", "c 3"]
        assert region["pages"] == [1, 2] and region["kept_page"] == 2

    def test_a_line_printed_on_both_pages_is_claimed_on_the_kept_one(self):
        from slot_extractor import select_region
        lines = [_line("Total 5", 1), _line("x 1", 2), _line("Total 5", 2),
                 _line("y 9", 1)]
        kept, region = select_region(
            self._located(lines, ["x 1", "Total 5", "y 9"]), lines, [])
        assert region["left_out"] == 1
        total = next(r for r in kept if r[1] == "Total 5")
        assert total[4] == [2]

    def test_a_row_placed_nowhere_is_not_left_out(self):
        from slot_extractor import select_region
        lines = [_line("a 1", 1), _line("b 2", 2)]
        kept, region = select_region(
            self._located(lines, ["a 1", "b 2", "invented"], model_page=0),
            lines, [])
        assert [s for _c, s, *_ in kept] == ["a 1", "invented"]

    def test_an_unlocated_row_falls_back_to_the_page_the_model_claimed(self):
        """Mapped through the prompt's page numbering to the FILE's."""
        from slot_extractor import select_region
        lines = [_line("a 1", 3), _line("b 2", 4)]
        page_lines = [[lines[0]], [lines[1]]]
        loc = self._located(lines, ["a 1"]) + [
            ({"a": "zz"}, "zz", 2, "zz", [])]
        kept, region = select_region(loc, lines, page_lines)
        assert region["pages"] == [3, 4] and len(kept) == 1


class TestPagesAreStampedAtRead:
    def test_file_page_numbers(self, pdf_dir):
        import pdfplumber
        from text_layer import line_page, read_page
        with pdfplumber.open(pdf_dir / "round2" / "feb2225.pdf") as pdf:
            got = [{line_page(ln) for ln in read_page(p)[1]} for p in pdf.pages]
        assert got == [{1}, {2}]

    def test_the_text_is_unchanged(self, pdf_dir):
        """The stamp is geometry only; the prompt text — and so every cached
        answer — must not move."""
        import pdfplumber
        from text_layer import read_page
        with pdfplumber.open(pdf_dir / "round2" / "feb2225.pdf") as pdf:
            for p in pdf.pages:
                assert read_page(p)[0] == (p.extract_text() or "")


# ══════════════════════════════════════════════════════════════════════════
# LIVE RUNS RECORDED AFTER THE FIX — replayed
# ══════════════════════════════════════════════════════════════════════════

class TestRun9AbsentFieldsStayEmpty:
    """Round 2's strongest single result (report line 211): every field absent
    from the ENGIE bill came back empty, including Customer Tax ID against the
    near-match `Fed. I.D. 76-0685946`. The fix changed its conditions — the
    bill is no longer split, so the model answers pages 1-4 in ONE prompt —
    so it was re-run live (tests/fixtures/round2_raw/run9_engie_BR4.json).

    BR4 is a reconstruction: only Customer Tax ID is named by the report as
    absent. The other three absent probes are guesses, each with a near-match.
    """

    @pytest.fixture(scope="class")
    def fields(self):
        results, _grid, _log = round2.run("run9_engie_BR4", mode="replay")
        ed = results[0].extracted_data
        return ({k: v["value"] for k, v in ed["extracted_data"].items()},
                ed["validation"]["confidence_map"])

    @pytest.mark.parametrize("absent", ["Customer Tax ID", "Late Fee Amount",
                                        "Deposit Amount"])
    def test_absent_field_is_empty(self, fields, absent):
        values, _conf = fields
        assert absent not in values, values.get(absent)

    def test_the_fed_id_is_nowhere_in_the_answer(self, fields):
        values, _conf = fields
        assert not any("76-0685946" in str(v) for v in values.values())

    def test_the_contract_end_date_is_not_a_prose_fragment(self, fields):
        """Run 9 answered `the last day of October 2020` (I11). This run left
        it empty — not a fix, just a different answer; recorded, not claimed."""
        values, _conf = fields
        assert "Contract End Date" not in values

    @pytest.mark.known_bug
    @pytest.mark.xfail(strict=True, reason=(
        "Customer Email Address is answered with ENGIE's own customer-care "
        "address at HIGH confidence: a real, grounded string for a field the "
        "document does not answer. PREDATES I1 — the pre-fix run reproduces it "
        "(round2_raw/run9_engie_BR4_prefix_fe3385d.json). Nothing checks that "
        "a quoted span means what the slot's label asks for."))
    def test_the_suppliers_email_is_not_the_customers(self, fields):
        values, conf = fields
        assert values.get("Customer Email Address", "") == ""

    def test_the_pre_fix_run_returned_the_same_address(self):
        """Recorded at fe3385d, where the bill was split: the pages 1-3 part
        answered the care address too, so I1 did not cause it. The same run
        reproduces round-2 run 9's other outputs (the interleaved account
        number, `Aug 12 / Sep 11`, the prose Contract End Date), which is some
        evidence the BR4 reconstruction is close for those fields."""
        rec = json.loads((round2.RAW_DIR / "run9_engie_BR4_prefix_fe3385d.json")
                         .read_text(encoding="utf-8"))
        assert rec["commit"].startswith("fe3385d")
        answers = [json.loads(r["raw_llm_responses"][0])["fields"]
                   for r in rec["responses"]]
        assert len(answers) == 2
        emails = [a[k]["value"] for a in answers for k in a
                  if "engieresources" in str(a[k].get("value", ""))]
        assert emails == ["care@engieresources.com"]
        assert any(a[k]["value"] == "00000000112538645596"
                   for a in answers for k in a)


class TestRun2PageTwoTemplateGetsPageTwo:
    """B2 targets Berkshire's page-2 operating-earnings table. Recorded live
    (tests/fixtures/round2_raw/run2_berkshire_B2.json).

    ⚠ The model returned ONLY page-2 rows, so `select_region` had nothing to
    choose between. This pins the right outcome on this input; it does NOT
    verify "keep the page the answer begins on" for a page-2 template."""

    @pytest.fixture(scope="class")
    def ed(self):
        results, _grid, _log = round2.run("run2_berkshire_B2", mode="replay")
        assert len(results) == 1
        return results[0].extracted_data

    def test_the_page_two_table_is_written(self, ed):
        items = [r["Business"] for r in ed["Operating Earnings_rows"]]
        assert items[:3] == ["Insurance-underwriting",
                             "Insurance-investment income", "BNSF"]
        assert len(items) == 8

    def test_no_page_one_row_is_in_it(self, ed):
        items = " ".join(r["Business"] for r in ed["Operating Earnings_rows"])
        assert "Net earnings attributable" not in items
        assert "Class A" not in items

    def test_no_second_region_was_offered(self, ed):
        assert ed["validation"]["regions"] == []
