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
    def test_not_one_of_them(self, page_texts):
        """Every document in the corpus, on its own. A split here shreds a
        real document into fragments.

        This now includes `201403_cfpb_closing-disclosure_cover-H25B.pdf` —
        the six-page form that exposed the over-split, and the corpus's first
        multi-page SINGLE document. Before it, all 17 multi-page documents
        were two-page financial statements whose second page is a continuation
        with a different first line, so "0 false positives across 60
        documents" was a true statement about a condition the corpus could not
        express."""
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


# ══════════════════════════════════════════════════════════════════════════
# THE CASE THE CORPUS COULD NOT EXPRESS
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def closing_disclosure(repo_dir):
    """A five-page form that restates its parties on every page.

    The corpus has 60 documents and 17 of them are multi-page, so a false
    positive WAS observable — but not one of those 17 reopens with its own
    title, which is the exact condition that breaks a title-repetition rule.
    "0 false positives across 60 documents" was therefore a true statement
    about a condition the corpus cannot express, and this was the first real
    multi-page form ever put through the splitter. It split on the first try.
    """
    import json
    return json.loads(
        (repo_dir / "tests/fixtures/closing_disclosure_pages.json").read_text(
            encoding="utf-8"))


class TestTheRealClosingDisclosure:
    """The actual file, not a reconstruction.

    Six pages: a cover sheet plus the five-page form. Every page from the
    second on prints `PAGE n OF 5` and repeats `Loan ID # 123456789`.
    """

    @pytest.fixture(scope="class")
    def cd(self, pdf_dir):
        import pdfplumber
        with pdfplumber.open(
                pdf_dir / "201403_cfpb_closing-disclosure_cover-H25B.pdf") as p:
            return [pg.extract_text() or "" for pg in p.pages]

    def test_it_is_one_document(self, cd):
        got, why = find_starts(cd)
        assert got == [0], (got, why)

    def test_two_of_its_pages_classify_as_other_document_types(self, cd):
        """This is why it split, and why the page-count veto is load-bearing
        rather than decorative: page 4 reads as a bank statement and page 6 as
        a tax form. Type change is otherwise an uncorroborated boundary."""
        from doc_boundaries import _doc_type
        types = [_doc_type(t) for t in cd]
        assert types[3] == "bank_statement"
        assert types[5] == "tax_form"

    def test_the_form_states_its_own_extent_on_every_page_but_the_cover(self, cd):
        from doc_boundaries import page_of
        assert [page_of(t) for t in cd] == [None, (1, 5), (2, 5), (3, 5),
                                            (4, 5), (5, 5)]

    def test_the_loan_id_recurs_but_not_perfectly(self, cd):
        """Four of the five form pages carry `123456789`. The fifth prints
        `LOAN ID # 1234567890` — ten digits — in the published CFPB sample
        itself.

        That is the argument against leaning on reference continuity alone:
        a real document's own reference chain has a typo in it. The page-count
        veto is what carries the split across the break, and this test exists
        so that nobody later "simplifies" the veto away."""
        from doc_boundaries import references
        with_id = [t for t in cd[1:] if "123456789" in references(t)]
        assert len(with_id) == 4
        assert "1234567890" in references(cd[4])

    def test_it_stays_one_document_across_that_break(self, cd):
        assert find_starts(cd)[0] == [0]

    def test_the_whole_file_reaches_extraction_as_one_slice(self, cd):
        slices, _why = split(cd)
        assert len(slices) == 1
        assert len(slices[0][0]) == 6


class TestAMultiPageFormIsOneDocument:
    @pytest.mark.parametrize("variant", ["distinct_headings",
                                         "tail_repeats_title",
                                         "running_header"])
    def test_it_does_not_split(self, closing_disclosure, variant):
        """All three shapes, because which one a generator produces decides
        whether the old rule fired: `tail_repeats_title` cut the form in two
        and `running_header` cut it into five."""
        pages = closing_disclosure["variants"][variant]
        got, why = find_starts(pages)
        assert got == [0], (got, why)

    def test_the_contact_page_is_not_a_document_of_its_own(
            self, closing_disclosure):
        """The reported failure exactly: a near-empty second block carrying
        only the three values the contact page restates."""
        pages = closing_disclosure["variants"]["tail_repeats_title"]
        slices, _why = split(pages)
        assert len(slices) == 1
        assert len(slices[0][0]) == 5

    def test_every_page_shares_the_loan_id(self, closing_disclosure):
        """The signal that saves it. Recurrence of a reference means
        CONTINUATION — the old rule read it as a boundary."""
        from doc_boundaries import references
        pages = closing_disclosure["variants"]["distinct_headings"]
        shared = set.intersection(*[references(p) for p in pages])
        assert "123456789" in shared

    def test_the_form_states_its_own_extent(self, closing_disclosure):
        from doc_boundaries import page_of
        pages = closing_disclosure["variants"]["distinct_headings"]
        assert [page_of(p) for p in pages] == [(1, 5), (2, 5), (3, 5),
                                               (4, 5), (5, 5)]


class TestCorroborationAndVeto:
    def test_a_repeated_title_alone_no_longer_splits(self):
        """A repeated title means "a new document" in a concatenation and "a
        continuation" in a form — the SAME observation. It is now a candidate,
        not a verdict."""
        pages = ["ACME FORM\nRef No 778899\nSection A",
                 "ACME FORM\nRef No 778899\nSection B"]
        assert find_starts(pages)[0] == [0]

    def test_a_repeated_title_WITH_a_new_reference_still_splits(self):
        pages = ["ACME FORM\nRef No 778899\nSection A",
                 "ACME FORM\nRef No 112233\nSection A"]
        assert find_starts(pages)[0] == [0, 1]

    def test_a_numbered_run_vetoes_a_split_inside_it(self):
        """"Page 2 of 3" after "page 1 of 3" is the document saying outright
        that these are one document."""
        pages = ["ACME FORM Page 1 of 3\nRef No 778899\nA",
                 "ACME FORM Page 2 of 3\nRef No 445566\nB",
                 "ACME FORM Page 3 of 3\nRef No 990011\nC"]
        assert find_starts(pages)[0] == [0]

    def test_the_veto_is_per_run_not_per_file(self):
        """A stack of forms each opening at "page 1 of 2" must still split
        between them — a per-file reading of the same marker would have
        treated the whole stack as one document."""
        pages = ["ACME FORM Page 1 of 2\nRef No 778899\nA",
                 "ACME FORM Page 2 of 2\nRef No 778899\nB",
                 "ACME FORM Page 1 of 2\nRef No 112233\nA",
                 "ACME FORM Page 2 of 2\nRef No 112233\nB"]
        assert find_starts(pages)[0] == [0, 2]

    def test_a_restart_splits_even_when_the_reference_is_identical(self):
        """Two copies of ONE form share every reference, so nothing but the
        document's own page count can see the seam. This is the single
        boundary allowed without a reference change."""
        pages = ["ACME FORM Page 1 of 2\nRef No 778899\nA",
                 "ACME FORM Page 2 of 2\nRef No 778899\nB",
                 "ACME FORM Page 1 of 2\nRef No 778899\nA",
                 "ACME FORM Page 2 of 2\nRef No 778899\nB"]
        assert find_starts(pages)[0] == [0, 2]


class TestItUnderSplitsRatherThanOverSplits:
    def test_a_concatenation_with_no_readable_reference_stays_one_document(self):
        """The cost of the fix, taken deliberately. Falling back to the old
        title rule here would reintroduce over-splitting exactly where there
        is least information to justify it. Recorded in KNOWN-LIMITATIONS."""
        pages = ["DELIVERY NOTE\nGoods received in good order",
                 "DELIVERY NOTE\nGoods received in good order"]
        assert find_starts(pages)[0] == [0]
