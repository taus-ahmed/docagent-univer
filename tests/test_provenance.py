"""I2 — every value reaches the sheet with where it came from.

Round 2: "Every merged block arrives with no indication of where it came from."
A band bound to the wrong region, a glossary row that looks like a charge line,
a second document stacked under the first: each is silent in the export,
because nothing on the sheet says which document or page a row was read from.

Two things now travel with the values:

  * a SOURCE column, right of the template, on every row carrying extracted
    values: the document's name and the file page it was read from
  * a CELL COMMENT on every extracted value holding the exact words it was read
    from, so hovering a cell shows the quote, the document and the page. A
    value whose quote could not be verified says so in the comment.

The page is the FILE page, read off the geometry of the line the value was
claimed from (I1 stamps it on every word), never the model's own page number
when geometry can answer.

Everything here runs the real pipeline on the committed documents from the
recorded cache.
"""
import contextlib
import io
import re
import tempfile

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()


def _pages_text(pdf):
    import pdfplumber
    from text_layer import read_page
    with pdfplumber.open(pdf) as doc:
        return [read_page(p)[0] for p in doc.pages]


def _on_page(value, text):
    """Is `value` printed on this page? A number as a whole printed number;
    text as a whitespace- and case-insensitive substring."""
    from slot_extractor import _flat, _number_key, printed_numbers
    key = _number_key(value)
    if key is not None:
        return any(_number_key(t) == key for t in printed_numbers(text))
    return _flat(value) in _flat(text)


@pytest.fixture(scope="module")
def gold_runs(replay_cache):
    """Every gold document, templated, through the real pipeline."""
    from tests.harness import runner
    _bs.chdir_backend()
    out = {}
    for lab in runner.load_labels():
        td, grid, _ = runner.build_template_data(lab, "replay")
        with contextlib.redirect_stdout(io.StringIO()):
            results, _log = runner.run_pipeline(lab, td)
        out[lab["document_id"]] = (lab, grid, results)
    return out


@pytest.fixture(scope="module")
def merged(replay_cache):
    """Three invoices in one PDF, through run_extraction (the split happens
    before slot extraction)."""
    from tests.harness import scenarios as S
    from connectors.llm_router import LLMRouter
    _bs.chdir_backend()
    sc = S.load("multi_document")[0]
    replay_cache.context = sc["name"]
    with contextlib.redirect_stdout(io.StringIO()):
        return S.run(sc, tempfile.mkdtemp(), type("O", (), {"llm": LLMRouter()})())


# ══════════════════════════════════════════════════════════════════════════
# the extraction result carries it
# ══════════════════════════════════════════════════════════════════════════

class TestEveryValueKnowsWhereItCameFrom:
    def test_every_field_value_has_its_quote_and_page(self, gold_runs):
        missing = []
        for doc, (_lab, _g, results) in gold_runs.items():
            ed = results[0].extracted_data
            prov = ed.get("field_provenance") or {}
            for ref in ed["extracted_fields"]:
                p = prov.get(ref) or {}
                if not str(p.get("source", "")).strip() or not p.get("page"):
                    missing.append((doc, ref, p))
        assert not missing, missing[:10]

    def test_every_table_row_has_its_quote_and_page(self, gold_runs):
        missing, rows = [], 0
        for doc, (_lab, _g, results) in gold_runs.items():
            ed = results[0].extracted_data
            for key, val in ed.items():
                if not key.endswith("_rows"):
                    continue
                for i, row in enumerate(val):
                    rows += 1
                    if not str(row.get("_source", "")).strip() or not row.get("_page"):
                        missing.append((doc, key, i))
        assert rows > 50 and not missing, (rows, missing[:10])

    def test_the_page_is_the_page_the_value_is_printed_on(self, gold_runs, pdf_dir):
        """The general check, over every grounded value of every gold
        document: the page recorded is a page that prints the value."""
        wrong, checked, pages_seen = [], 0, set()
        for doc, (lab, _g, results) in gold_runs.items():
            ed = results[0].extracted_data
            texts = _pages_text(pdf_dir / lab["pdf"])
            conf = ed["validation"]["confidence_map"]
            for ref, value in ed["extracted_fields"].items():
                p = (ed.get("field_provenance") or {}).get(ref) or {}
                if not p.get("grounded") or conf.get(ref) == "low":
                    continue
                checked += 1
                pages_seen.add((doc, p["page"]))
                if not _on_page(value, texts[p["page"] - 1]):
                    wrong.append((doc, ref, value, p["page"]))
            for key, val in ed.items():
                if not key.endswith("_rows"):
                    continue
                for row in val:
                    if row.get("_confidence") == "low":
                        continue
                    for col, v in row.items():
                        if col.startswith("_") or not str(v).strip():
                            continue
                        checked += 1
                        pages_seen.add((doc, row["_page"]))
                        if not _on_page(v, texts[row["_page"] - 1]):
                            wrong.append((doc, key, col, v, row["_page"]))
        # 386 = every confident value in the gold corpus: 109 fields, 277 row
        # cells (89 rows). All 89 rows are page 1 (the page-2 continuations are
        # the rows I1 leaves out), so page 2 comes from fields: 9 of 115.
        assert checked >= 386 and not wrong, (checked, wrong[:10])
        assert any(p > 1 for _d, p in pages_seen), "no value came from page 2+"

    def test_a_document_split_out_of_a_file_reports_file_pages(self, merged):
        """Three invoices, one per page: the third invoice's values are on page
        3 of the FILE, not page 1 of its own slice."""
        assert [d["source_pages"] for d in merged] == [[1, 1], [2, 2], [3, 3]]
        for n, ed in enumerate(merged, start=1):
            pages = {p["page"] for p in (ed.get("field_provenance") or {}).values()}
            pages |= {r["_page"] for k, v in ed.items()
                      if k.endswith("_rows") for r in v}
            assert pages == {n}, (n, pages)


# ══════════════════════════════════════════════════════════════════════════
# the sheet carries it
# ══════════════════════════════════════════════════════════════════════════

def _export(results, grid, **kw):
    import json
    import openpyxl
    from app.api.routes.extract import _analyse_template_regions, _write_excel
    from app.models.models import DocumentResult
    docs = [DocumentResult(filename=r.filename, document_type="x",
                           extraction_json=json.dumps(r.extracted_data, default=str))
            for r in results]
    wb = openpyxl.Workbook()
    with contextlib.redirect_stdout(io.StringIO()):
        _write_excel(wb.active, docs, grid, _analyse_template_regions(grid),
                     openpyxl, **kw)
    return wb.active


def _cells(ws):
    return {c.coordinate: c.value for row in ws.iter_rows() for c in row
            if c.value is not None}


class TestTheSheetShowsWhereEachValueCameFrom:
    @pytest.mark.parametrize("doc", ["STMT-2024-01", "BS-2024-Q1", "INV-2024-0031"])
    def test_every_extracted_value_has_a_comment_quoting_its_source(self, gold_runs, doc):
        lab, grid, results = gold_runs[doc]
        ed = results[0].extracted_data
        ws = _export(results, grid)
        values = set()
        for v in ed["extracted_fields"].values():
            values.add(str(v).strip())
        for key, val in ed.items():
            if key.endswith("_rows"):
                for row in val:
                    values |= {str(x).strip() for k, x in row.items()
                               if not k.startswith("_") and str(x).strip()}
        without = []
        commented = 0
        for row in ws.iter_rows():
            for c in row:
                if c.comment is not None:
                    commented += 1
                    assert re.search(r"page \d+", c.comment.text), c.comment.text
                    assert lab["pdf"] in c.comment.text, c.comment.text
        assert commented >= len(values) * 0.9, (commented, len(values))

    def test_a_row_comment_is_the_exact_quote_the_row_was_read_from(self, gold_runs):
        _lab, grid, results = gold_runs["STMT-2024-01"]
        ed = results[0].extracted_data
        rows = next(v for k, v in ed.items() if k.endswith("_rows") and v)
        quotes = {" ".join(str(r["_source"]).split()) for r in rows}
        ws = _export(results, grid)
        seen = {m.group(1) for row in ws.iter_rows() for c in row if c.comment
                for m in [re.search(r"“(.*)”", c.comment.text, re.S)] if m}
        assert quotes <= seen, sorted(quotes - seen)[:3]

    def test_every_table_row_has_a_source_cell(self, gold_runs):
        _lab, grid, results = gold_runs["STMT-2024-01"]
        ed = results[0].extracted_data
        rows = next(v for k, v in ed.items() if k.endswith("_rows") and v)
        ws = _export(results, grid)
        src = [c.value for row in ws.iter_rows() for c in row
               if isinstance(c.value, str) and c.value.startswith("STMT-2024-01.pdf · p.")]
        assert len(src) >= len(rows), (len(src), len(rows))
        assert any(c.value == "Source" for row in ws.iter_rows() for c in row)

    def test_a_merged_file_names_each_document_and_its_file_page(self, merged):
        """The I2 case itself: three stacked blocks, each row saying which
        document and page it is."""
        import openpyxl
        from tests.harness import scenarios as S

        class _R:
            def __init__(self, ed, n):
                self.extracted_data, self.filename = ed, f"merged.pdf [{n} of 3]"
        sc = S.load("multi_document")[0]
        ws = _export([_R(ed, n) for n, ed in enumerate(merged, 1)], sc["grid"])
        labels = {c.value for row in ws.iter_rows() for c in row
                  if isinstance(c.value, str) and c.value.startswith("merged.pdf [")}
        assert labels >= {"merged.pdf [1 of 3] · p.1", "merged.pdf [2 of 3] · p.2",
                          "merged.pdf [3 of 3] · p.3"}, labels

    def test_an_unverified_quote_says_so(self, gold_runs):
        """A value whose quoted span was not found must not be presented as a
        verbatim quote."""
        from app.api.routes.extract import provenance_note
        text = provenance_note("Wrong words", 2, "x.pdf", grounded=False,
                               confidence="low")
        assert text.startswith("Not verified")
        assert "x.pdf, page 2" in text
        assert "low" not in text.casefold(), "confidence stays in the app"
        ok = provenance_note("Opening Balance $184,320.55", 1, "x.pdf",
                             grounded=True, confidence="high")
        assert ok.splitlines()[0] == "“Opening Balance $184,320.55”"


class TestNothingElseOnTheSheetChanges:
    @pytest.mark.parametrize("doc", ["STMT-2024-01", "BS-2024-Q1", "INV-2024-0031",
                                     "PAYSLIP-EMP-0007-APR2024"])
    def test_the_values_are_identical_with_and_without_provenance(self, gold_runs, doc):
        _lab, grid, results = gold_runs[doc]
        on, off = _export(results, grid), _export(results, grid, provenance=False)
        a, b = _cells(on), _cells(off)
        added = {k: v for k, v in a.items() if k not in b}
        assert {k: v for k, v in a.items() if k in b} == b
        assert all(v == "Source" or " · p." in str(v) or str(v).endswith(".pdf")
                   for v in added.values()), added
        assert not any(c.comment for row in off.iter_rows() for c in row)

    def test_an_old_job_without_provenance_exports_exactly_as_before(self, gold_runs):
        """Jobs stored before this change carry no provenance. They export with
        no comments and no source column — absent, not invented."""
        _lab, grid, results = gold_runs["STMT-2024-01"]

        class _Old:
            filename = "old.pdf"
            def __init__(self, ed):
                self.extracted_data = {k: (v if not (k.endswith("_rows") and isinstance(v, list))
                                           else [{c: x for c, x in r.items()
                                                  if c not in ("_source", "_page", "_ungrounded")}
                                                 for r in v])
                                       for k, v in ed.items() if k != "field_provenance"}
        old = _export([_Old(results[0].extracted_data)], grid)
        off = _export(results, grid, provenance=False)
        assert _cells(old) == _cells(off)
        assert not any(c.comment for row in old.iter_rows() for c in row)


class TestATransposedTableCarriesItInComments:
    """A transposed table lays each record down a COLUMN, so a record has no row
    of its own to put a Source cell on. Its provenance travels in the comments.
    (The first version of this writer recorded a row for it and crashed the
    export — caught by test_transposed_case.py, not by anything here.)"""

    def test_every_record_value_is_commented_and_no_source_cell_is_invented(
            self, replay_cache):
        from tests.harness.runner import (build_template_data, load_labels,
                                          run_pipeline)
        _bs.chdir_backend()
        label = load_labels({"PAYSLIP-EMP-0007-APR2024"})[0]
        td, grid, _ = build_template_data(label, "replay",
                                          template_override="payslip_transposed.json")
        with contextlib.redirect_stdout(io.StringIO()):
            results, _log = run_pipeline(label, td)
        ed = results[0].extracted_data
        tables = [t for t in ed["slot_map"]["tables"] if t.get("orientation") == "columns"]
        assert tables, "premise: the template is transposed"
        ws = _export(results, grid)
        checked = 0
        for t in tables:
            for i, rec in enumerate(ed[f"{t['name']}_rows"]):
                col = t["start_col"] + i + 1
                for c in ws.iter_cols(min_col=col, max_col=col):
                    for cell in c:
                        if cell.value is not None and cell.row - 1 in {
                                f["row"] for f in t["fields"]}:
                            assert cell.comment is not None, cell.coordinate
                            assert f"page {rec['_page']}" in cell.comment.text
                            checked += 1
        assert checked >= 11, checked      # 3 earnings + 8 deductions, x2 fields
        # The template's ordinary fields do get Source cells; the transposed
        # table's own rows must not, because they hold many records' values.
        record_rows = {f["row"] + 1 for t in tables for f in t["fields"]}
        assert not any(isinstance(c.value, str) and " · p." in c.value
                       for row in ws.iter_rows() for c in row
                       if c.row in record_rows)
