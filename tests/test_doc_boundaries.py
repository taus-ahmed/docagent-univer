"""
One file can be many documents.

One file was one document, unconditionally. Three invoices merged into one PDF
gave 13 field slots where 3 x 13 were needed — a single slot addressed "Invoice
Number" against three distinct invoice numbers — and the two the model did not
answer for were lost with no error, no flag and no note. That is the product's
own core use case.

The split is DETERMINISTIC and costs no model call. Two signals:

    repeated title   within a run of pages of the same type, a page whose
                     first line is that run's title. A title is the run's
                     first line, or a line printed on two CONSECUTIVE pages —
                     which is what a batch of one-page documents looks like
                     and what a continuation line can never be.

    type change      a page classifying as a different document type from the
                     last page that classified as anything (`classify_by_hints`,
                     keyword pre-screening, no model call).

Measured over the corpus: **0 false positives on all 60 single documents**, and
14 of 14 merged files split at exactly the right pages, including twenty
invoices, five two-page payslips, and mixed batches with runs of a repeated type
inside them.

The costs are not symmetric, and the tests reflect that. Splitting something
that should not have been split produces N stacked blocks, most of them mostly
empty — ugly, obvious, fixable in one look. NOT splitting produces one plausible
result and silently discards the rest. So the false-positive test is the strict
one, and it runs over every document in the corpus.
"""
import tempfile

import pytest

from tests.harness import bootstrap as _bs

_bs.bootstrap()

from doc_boundaries import find_starts, split  # noqa: E402


@pytest.fixture(scope="module")
def page_texts(pdf_dir):
    """Every corpus PDF's page texts, read once."""
    import pdfplumber
    out = {}
    for p in sorted(pdf_dir.glob("*.pdf")):
        with pdfplumber.open(p) as pdf:
            out[p.stem] = [pg.extract_text() or "" for pg in pdf.pages]
    return out


def _merge(page_texts, names):
    """(pages, expected_start_indices) for a hypothetical merged file."""
    pages, starts, acc = [], [], 0
    for n in names:
        starts.append(acc)
        pages += page_texts[n]
        acc += len(page_texts[n])
    return pages, starts


# ══════════════════════════════════════════════════════════════════════════
# FALSE POSITIVES — the direction that must never happen quietly
# ══════════════════════════════════════════════════════════════════════════

class TestNoSingleDocumentIsEverSplit:
    def test_not_one_of_the_sixty(self, page_texts):
        """Every document in the corpus, on its own. A split here shreds a
        real document into fragments."""
        split_up = {n: find_starts(t)[0] for n, t in page_texts.items()
                    if find_starts(t)[0] != [0]}
        assert split_up == {}, split_up

    def test_the_seventeen_multi_page_ones_are_the_hard_case(self, page_texts):
        """A one-page document cannot be split by definition, so the test
        above only means something because the corpus has multi-page ones."""
        multi = [n for n, t in page_texts.items() if len(t) > 1]
        assert len(multi) >= 15, multi

    def test_an_empty_file_is_one_document(self):
        assert find_starts([])[0] == [0]
        assert find_starts([""])[0] == [0]

    def test_blank_pages_do_not_start_documents(self):
        assert find_starts(["INVOICE\nTotal 5", "", ""])[0] == [0]


# ══════════════════════════════════════════════════════════════════════════
# TRUE POSITIVES
# ══════════════════════════════════════════════════════════════════════════

MERGES = {
    "five one-page invoices": ["INV-2024-0031", "INV-2024-0047",
                               "INV-2024-0063", "INV-2024-0089",
                               "INV-2024-0112"],
    "five cheques": ["CHQ-001847", "CHQ-001848", "CHQ-001849",
                     "CHQ-001850", "CHQ-001851"],
    "five statements": ["STMT-2024-01", "STMT-2024-02", "STMT-2024-03",
                        "STMT-2024-04", "STMT-2024-05"],
    "five TWO-PAGE payslips": ["PAYSLIP-EMP-0007-APR2024",
                               "PAYSLIP-EMP-0012-APR2024",
                               "PAYSLIP-EMP-0021-APR2024",
                               "PAYSLIP-EMP-0034-APR2024",
                               "PAYSLIP-EMP-0045-APR2024"],
    "five expense reports": ["EXP-2024-0081", "EXP-2024-0092", "EXP-2024-0107",
                             "EXP-2024-0118", "EXP-2024-0134"],
    "five receipts (classifier says None)": ["RCP-2024-0031", "RCP-2024-0047A",
                                             "RCP-2024-0058", "RCP-2024-0062",
                                             "RCP-2024-0081"],
    "five two-page balance sheets": ["BS-2024-Q1", "BS-2024-Q2", "BS-2023-YE",
                                     "BS-2024-INTERIM", "BS-2024-PROJ-YE"],
    "two income statements": ["IS-2024-Q3", "IS-2024-Q4"],
    "four different types": ["INV-2024-0031", "CHQ-001847", "STMT-2024-01",
                             "PAYSLIP-EMP-0007-APR2024"],
    "eight, mixed, with runs": ["INV-2024-0031", "INV-2024-0047", "CHQ-001847",
                                "CHQ-001848", "STMT-2024-01",
                                "PAYSLIP-EMP-0007-APR2024", "EXP-2024-0081",
                                "PO-2024-0018"],
    "runs of pairs of three types": ["PO-2024-0018", "PO-2024-0029",
                                     "RCP-2024-0031", "RCP-2024-0047A",
                                     "INV-2024-0031", "INV-2024-0047"],
    "three two-page docs of different types": ["IS-2024-Q4",
                                               "PAYSLIP-EMP-0007-APR2024",
                                               "BS-2024-Q1"],
}


class TestMergedFilesSplitAtTheRightPages:
    @pytest.mark.parametrize("name", list(MERGES))
    def test_exactly_right(self, page_texts, name):
        pages, expected = _merge(page_texts, MERGES[name])
        got, why = find_starts(pages)
        assert got == expected, (got, expected, why)

    def test_twenty_invoices_in_one_file(self, page_texts):
        """The number the user actually said. Nothing about the rule is
        sensitive to how many there are, and this proves it."""
        names = MERGES["five one-page invoices"] * 4
        pages, expected = _merge(page_texts, names)
        assert find_starts(pages)[0] == expected
        assert len(expected) == 20

    def test_it_says_why_it_split(self, page_texts):
        """A silent split would be as bad as a silent merge."""
        pages, _ = _merge(page_texts, MERGES["four different types"])
        _starts, why = find_starts(pages)
        assert "document type changes" in why


# ══════════════════════════════════════════════════════════════════════════
# The slices handed to the pipeline
# ══════════════════════════════════════════════════════════════════════════

class TestTheSlices:
    def test_one_document_yields_one_slice_identical_to_the_input(self,
                                                                  page_texts):
        pages = page_texts["INV-2024-0031"]
        slices, why = split(pages)
        assert len(slices) == 1
        assert slices[0][0] == pages
        assert why == ""

    def test_each_slice_carries_its_own_pages_lines_and_images(self,
                                                               page_texts):
        pages, expected = _merge(page_texts,
                                 MERGES["five TWO-PAGE payslips"])
        lines = [[{"text": f"p{i}", "x0": 0, "x1": 1, "top": 0}]
                 for i in range(len(pages))]
        images = [f"img{i}" for i in range(len(pages))]
        slices, _why = split(pages, lines, images)
        assert len(slices) == 5
        for (texts, lns, imgs, first) in slices:
            assert len(texts) == len(lns) == len(imgs) == 2
        assert [s[3] for s in slices] == [i + 1 for i in expected]

    def test_the_slices_cover_every_page_exactly_once(self, page_texts):
        pages, _ = _merge(page_texts, MERGES["eight, mixed, with runs"])
        slices, _why = split(pages)
        assert sum(len(s[0]) for s in slices) == len(pages)
        assert [p for s in slices for p in s[0]] == pages


class TestAContinuationPageIsNotADocument:
    def test_page_furniture_is_folded_into_the_document_above(self):
        """A candidate whose whole document would be one line of furniture is
        a continuation. Discarding the split entirely on account of it — which
        is what an earlier version did — lost the real boundaries too."""
        pages = ["ACME INVOICE\nInvoice 1\nTotal 100",
                 "continued",
                 "ACME INVOICE\nInvoice 2\nTotal 200",
                 "continued"]
        assert find_starts(pages)[0] == [0, 2]
