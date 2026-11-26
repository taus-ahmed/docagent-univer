"""Run S, Stage 3c — a multi-line value beside a label, in a two-column block.

Two labelled columns side by side; each value wraps INSIDE its own column.
The model's quote is the flattened line (it interleaves the other column),
so the value is not contiguous in it. The value is grounded when the page's
in-column reading spells it exactly without crossing a gutter AND it starts
where the quote's label is. All text is invented.

Negative twins: a value that crosses into the neighbouring column, and a
value whose first words are not at the quoted label, stay Low.
"""
from __future__ import annotations

import pytest

from tests import run_q_support as Q

# (label, first line, continuation lines) in the LEFT column; the right column
# carries another label with its own wrapped value
CASES = [
    ("Address", "12 Example Road", ["Sampletown, ST 00000", "Countryland"]),
    ("Remit To", "Example Supply Co", ["PO Box 4410", "Sampletown, ST 00000"]),
    ("Description", "Quarterly service for", ["two example units"]),
    ("Notes", "Deliver to the rear", ["loading dock only"]),
]
RIGHT = ("Ship To", "Other Example Ltd", ["88 Sample Avenue", "Othertown, ST 11111"])


def _items(label, first, rest):
    items = [(56, 770, "EXAMPLE DOCUMENT"),
             (56, 740, f"{label}: {first}"), (330, 740, f"{RIGHT[0]}: {RIGHT[1]}")]
    x_left = 56 + 5.0 * (len(label) + 2)
    x_right = 330 + 5.0 * (len(RIGHT[0]) + 2)
    for k in range(max(len(rest), len(RIGHT[2]))):
        y = 726 - 14 * k
        if k < len(rest):
            items.append((x_left, y, rest[k]))
        if k < len(RIGHT[2]):
            items.append((x_right, y, RIGHT[2][k]))
    return items


def _run(tmp_path, label, value, source):
    first, rest = None, None
    for lab, f, r in CASES:
        if lab == label:
            first, rest = f, r
    pdf = Q.make_pdf(tmp_path / "w.pdf", [_items(label, first, rest)], size=9)
    tpl = Q.template(fields=[label], doc_type="other")

    def answer(prompt):
        ids = Q.slot_ids(prompt)
        return {"fields": {ids[label]: {"value": value, "source": source, "page": 1}},
                "tables": {}}

    ed = Q.run(pdf, tpl, answer)[0].extracted_data
    ref = next(f["ref"] for f in ed["slot_map"]["fields"] if f["row_label"] == label)
    return ed["validation"]["confidence_map"].get(ref), ed["extracted_fields"].get(ref)


@pytest.mark.parametrize("label,first,rest", CASES)
def test_a_wrapped_value_in_its_own_column_is_not_low(tmp_path, label, first, rest):
    value = " ".join([first] + rest)
    flat = f"{label}: {first} {RIGHT[0]}: {RIGHT[1]} " + " ".join(rest)
    level, got = _run(tmp_path, label, value, flat)
    assert got == value
    assert level != "low", (label, level)


@pytest.mark.parametrize("label,first,rest", CASES)
def test_a_value_taking_the_other_columns_words_stays_low(tmp_path, label, first, rest):
    # the continuation is the RIGHT column's line, not its own
    value = f"{first} {RIGHT[2][0]}"
    flat = f"{label}: {first} {RIGHT[0]}: {RIGHT[1]} {RIGHT[2][0]}"
    level, _got = _run(tmp_path, label, value, flat)
    assert level == "low", (label, level)


@pytest.mark.parametrize("label,first,rest", CASES)
def test_a_value_not_starting_at_its_label_stays_low(tmp_path, label, first, rest):
    # the model answered with the OTHER column's value under this label
    value = " ".join([RIGHT[1]] + RIGHT[2])
    flat = f"{label}: {first} {RIGHT[0]}: {RIGHT[1]} " + " ".join(RIGHT[2])
    level, _got = _run(tmp_path, label, value, flat)
    assert level == "low", (label, level)
