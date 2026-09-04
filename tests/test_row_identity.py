"""
A row is identified by WHICH LINE it was read from, not by what that line says.

The old rule keyed a row on the text of its source span and dropped every later
row quoting the same words. That is only correct if the document prints those
words once. Two rows legitimately quoting one line is ordinary — a group header,
a repeated column heading, a document that prints the same line twice — and it
is *structural* in the case this product exists for: a file holding twenty
invoices repeats every identifying line twenty times.

Measured on the corpus before the fix, by merging real documents into one file:

    five invoices     9 lines repeat   33 rows deletable
    five cheques      6                24
    five statements   8                32
    five payslips    11 (incl. "Description Amount" x10)   43

Linear in the number of documents in the file. The tests here run that same
merge and require the rows to survive it.

The capability the old rule provided is kept, and sharpened: a fabricated row
is one claiming a document line that every copy of is already spoken for. Under
the text rule that was approximated by "quotes the same words as an earlier
row", which is a different statement and was wrong far more often than it was
right.
"""
import json

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from slot_extractor import run_slot_extraction  # noqa: E402
from template_shape import compute_shape  # noqa: E402
from text_layer import read_page, source_occurrences  # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# The lookup itself
# ══════════════════════════════════════════════════════════════════════════

def L(*texts, top):
    return [{"text": t, "x0": 10.0 + 40 * i, "x1": 40.0 + 40 * i,
             "top": top, "bottom": top + 10} for i, t in enumerate(texts)]


class TestSourceOccurrences:
    def test_a_line_printed_twice_gives_two_occurrences(self):
        lines = [L("Terms:", "Net", "30", top=10),
                 L("something", "else", top=30),
                 L("Terms:", "Net", "30", top=50)]
        assert source_occurrences(lines, "Terms: Net 30") == [0, 2]

    def test_an_exact_line_match_beats_a_partial_one(self):
        """A short quote must not claim half the document."""
        lines = [L("Total", "100", top=10),
                 L("Grand", "Total", "100", "extra", top=30)]
        assert source_occurrences(lines, "Total 100") == [0]

    def test_a_multi_line_source_is_matched_on_its_first_line(self):
        """A record spanning several printed lines is quoted as several
        lines, and no single line contains the whole span."""
        lines = [L("Marcus", "A.", "Thompson", top=10),
                 L("Box", "1", "$87,500.00", top=30)]
        assert source_occurrences(
            lines, "Marcus A. Thompson\nBox 1 $87,500.00") == [0]

    def test_an_absent_source_gives_nothing(self):
        assert source_occurrences([L("a", "b", top=10)], "not here") == []

    def test_an_empty_source_gives_nothing(self):
        assert source_occurrences([L("a", top=10)], "") == []


# ══════════════════════════════════════════════════════════════════════════
# Through the pipeline
# ══════════════════════════════════════════════════════════════════════════

def _stub(payload):
    class _Resp:
        success = True
        parsed_json = payload
        raw_text = json.dumps(payload)

    class _LLM:
        def extract(self, **kw):
            return _Resp()

    return type("O", (), {"llm": _LLM()})()


GRID = {
    "cells": {"0,0": {"value": "Description"}, "0,1": {"value": "Amount"}},
    "colWidths": [], "merges": {}, "repeatRows": [],
    "regions": [{"type": "table", "r1": 0, "c1": 0, "r2": 60, "c2": 1,
                 "orientation": "rows", "name": "Items"}],
}


def _run(rows, text, lines):
    shape = compute_shape(GRID, log=lambda _m: None)
    payload = {"fields": {}, "tables": {"Items": rows}}
    return run_slot_extraction(
        _stub(payload), "DOC.pdf", {"layout": GRID, "shape": shape}, None,
        page_images=[], doc_text=text, doc_text_pages=[text],
        file_type="digital_pdf", default_doc_type="other", start=0.0,
        page_lines=lines)[0].extracted_data


@pytest.fixture(scope="module")
def merged_invoices(pdf_dir, tmp_path_factory):
    """Five real invoices in ONE file — the core use case."""
    from pypdf import PdfReader, PdfWriter
    names = ["INV-2024-0031", "INV-2024-0047", "INV-2024-0063",
             "INV-2024-0089", "INV-2024-0112"]
    out = tmp_path_factory.mktemp("merged") / "five_invoices.pdf"
    w = PdfWriter()
    for n in names:
        for p in PdfReader(str(pdf_dir / f"{n}.pdf")).pages:
            w.add_page(p)
    w.write(str(out))

    import pdfplumber
    texts, lines = [], []
    with pdfplumber.open(out) as pdf:
        for page in pdf.pages:
            t, ln, _ = read_page(page)
            texts.append(t)
            lines.append(ln)
    return "\n\n".join(texts), lines


class TestItHoldsAtTwentyInvoicesInOneFile:
    def test_the_repeated_line_really_does_repeat(self, merged_invoices):
        """Guard on the premise: if the fixture stopped repeating lines the
        tests below would pass for the wrong reason."""
        _, lines = merged_invoices
        flat = [ln for pg in lines for ln in pg]
        assert len(source_occurrences(flat, "Terms: Net 30")) >= 5

    def test_every_row_quoting_a_repeated_line_survives(self, merged_invoices):
        """Five rows read off five different invoices' identical Terms line.
        The old rule kept ONE and deleted four, silently."""
        text, lines = merged_invoices
        flat = [ln for pg in lines for ln in pg]
        n = len(source_occurrences(flat, "Terms: Net 30"))
        rows = [{"cells": {"Description": f"Invoice {i + 1} terms",
                           "Amount": f"{i + 1}"},
                 "source": "Terms: Net 30", "page": 1} for i in range(n)]
        ed = _run(rows, text, lines)
        assert len(ed["Items_rows"]) == n
        assert ed["validation"]["dropped_row_count"] == 0

    def test_one_row_more_than_the_document_has_copies_is_dropped(
            self, merged_invoices):
        """The fabricated-row case still holds — sharpened, not lost."""
        text, lines = merged_invoices
        flat = [ln for pg in lines for ln in pg]
        n = len(source_occurrences(flat, "Terms: Net 30"))
        rows = [{"cells": {"Description": f"row {i}", "Amount": f"{i}"},
                 "source": "Terms: Net 30", "page": 1} for i in range(n + 1)]
        ed = _run(rows, text, lines)
        assert len(ed["Items_rows"]) == n
        assert ed["validation"]["dropped_row_count"] == 1

    def test_line_items_from_every_invoice_survive_together(
            self, merged_invoices):
        """Different invoices, different lines, nothing shared: none of this
        should ever have been at risk, and it must stay that way."""
        text, lines = merged_invoices
        import re
        srcs = [l for l in text.split("\n")
                if re.match(r"^INV-2024-\d+", l.strip())]
        rows = [{"cells": {"Description": s[:20], "Amount": "1.00"},
                 "source": s, "page": 1} for s in srcs]
        ed = _run(rows, text, lines)
        assert len(ed["Items_rows"]) == len(rows)


class TestWithoutGeometryItStillDoesNotEatRealRows:
    """The image path and every caller predating positional evidence pass no
    lines. Identity there is the source PLUS the row's own values, so two
    different rows quoting one line both survive."""

    def test_two_different_rows_on_one_quoted_line_both_survive(self):
        text = "Subtotal: $100.00\nSubtotal: $100.00\n"
        rows = [{"cells": {"Description": "Group A", "Amount": "$100.00"},
                 "source": "Subtotal: $100.00", "page": 1},
                {"cells": {"Description": "Group B", "Amount": "$100.00"},
                 "source": "Subtotal: $100.00", "page": 1}]
        ed = _run(rows, text, None)
        assert len(ed["Items_rows"]) == 2

    def test_a_row_repeated_verbatim_is_still_dropped(self):
        text = "Subtotal: $100.00\n"
        row = {"cells": {"Description": "Group A", "Amount": "$100.00"},
               "source": "Subtotal: $100.00", "page": 1}
        ed = _run([row, dict(row)], text, None)
        assert len(ed["Items_rows"]) == 1
        assert ed["validation"]["dropped_row_count"] == 1


class TestAGroupedTableKeepsItsStructureRows:
    def test_headers_items_and_totals_all_survive_one_band(self, pdf_dir):
        """The D1/D2 shape: group headers, line items and totals in ONE band.
        Nothing here shares a source line, so nothing may be dropped."""
        import pdfplumber
        with pdfplumber.open(pdf_dir / "IS-2024-Q4.pdf") as pdf:
            pages = [read_page(p) for p in pdf.pages]
        text = "\n\n".join(t for t, _, _ in pages)
        lines = [ln for _, ln, _ in pages]
        printed = [l.strip() for l in text.split("\n") if l.strip()]
        wanted = [l for l in printed
                  if l.startswith(("REVENUE", "Gross Sales", "Total COGS",
                                   "GROSS PROFIT", "OPERATING EXPENSES",
                                   "Total Operating Expenses"))]
        rows = [{"cells": {"Description": l.split("$")[0].strip(),
                           "Amount": ("$" + l.split("$")[1]) if "$" in l else ""},
                 "source": l, "page": 1} for l in wanted]
        ed = _run(rows, text, lines)
        assert len(ed["Items_rows"]) == len(rows)
        assert ed["validation"]["dropped_row_count"] == 0
