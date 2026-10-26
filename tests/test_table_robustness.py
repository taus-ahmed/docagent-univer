"""Table robustness (Part 3.5): a table the document says continues is read
across its pages; anything less stays one region and is flagged. Property-
style checks run over seeded random tables (no hypothesis dependency)."""
import random

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from slot_extractor import continued_pages  # noqa: E402

HEAD = ["Date", "Description", "Amount"]


def _lines(pages):
    """[[word]] lines with page stamps, from {page: [text line]}."""
    out = []
    for p, texts in pages.items():
        for t in texts:
            out.append([{"text": w, "page": p} for w in t.split()])
    return out


def _page(n, of, heading=True, rows=2):
    lines = ["ACCOUNT STATEMENT", f"Page {n} of {of}"]
    if heading:
        lines.append(" ".join(HEAD))
    lines += [f"2024-04-0{k + 1} Item {n}-{k} $1{k}.00" for k in range(rows)]
    return lines


def test_a_numbered_run_with_its_heading_on_every_page_continues():
    pages = {p: _page(p, 4) for p in range(1, 5)}
    assert continued_pages(1, _lines(pages), HEAD) == {2, 3, 4}


@pytest.mark.parametrize("case,pages", [
    ("no heading on page 2", {1: _page(1, 3), 2: _page(2, 3, heading=False), 3: _page(3, 3)}),
    ("heading but no numbering",
     {1: ["T", " ".join(HEAD), "a b $1.00"], 2: ["T", " ".join(HEAD), "c d $2.00"]}),
    ("numbering skips a page", {1: _page(1, 5), 2: _page(3, 5)}),
    ("a different run", {1: _page(1, 2), 2: _page(2, 3)}),
])
def test_anything_less_does_not_continue(case, pages):
    assert continued_pages(1, _lines(pages), HEAD) == set(), case


def test_a_single_column_heading_never_continues():
    pages = {1: ["Page 1 of 2", "Amount", "$1.00"], 2: ["Page 2 of 2", "Amount", "$2.00"]}
    assert continued_pages(1, _lines(pages), ["Amount"]) == set()


@pytest.mark.parametrize("seed", range(25))
def test_property_continuation_stops_at_the_first_page_that_breaks_the_run(seed):
    rng = random.Random(seed)
    n = rng.randrange(2, 9)
    brk = rng.randrange(2, n + 2)          # the first page that breaks (n+1 = none)
    pages = {}
    for p in range(1, n + 1):
        broken = p == brk
        kind = rng.choice(("heading", "number")) if broken else None
        pages[p] = _page(p if kind != "number" else p + 1, n, heading=kind != "heading")
    got = continued_pages(1, _lines(pages), HEAD)
    assert got == set(range(2, min(brk, n + 1)))
