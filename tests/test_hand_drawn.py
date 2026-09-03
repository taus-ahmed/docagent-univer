"""
The five templates a user actually draws by hand.

Every fixture in `tests/gold/hand_drawn/` holds ONLY the cells someone typed —
no styling, no bordered blocks, no `extractTarget` markers. That matters: the
nine templates in `tests/gold/templates/` were produced by the old marker tool,
which materialised an explicit empty cell for every slot, and the two in
`tests/fixtures/prod_templates/` work because a user happened to drag a border
over the value column (bank_statement_101: 29 explicit-empty cells, all 29
carrying a style). So the committed corpus satisfied a precondition the editor
never satisfies, and the harness could read 98.5% while everything drawn by
hand scored zero slots.

These are the counter-corpus. Each expectation is what the person who drew the
template would say the answer obviously is.

All fifteen expectations pass as of R3. They were 4/15 before R1, 11/15 after
R1+R4, and 13/15 after R2 — the corpus is here to keep that from regressing,
not to record a snapshot.
"""
import json

from tests.harness import bootstrap as bs  # noqa: F401  (puts engine on sys.path)
from template_shape import compute_shape, is_usable  # noqa: E402

HAND_DRAWN = bs.GOLD_DIR / "hand_drawn"


def _shape(slug):
    return compute_shape(json.loads((HAND_DRAWN / f"{slug}.json").read_text()))


def _slots(shape):
    return {f["ref"] for f in shape["field_slots"]}


# ══════════════════════════════════════════════════════════════════════════════
# 1 ── a plain label/value list
# ══════════════════════════════════════════════════════════════════════════════

class TestAPlainLabelValueList:
    """Labels down column A and nothing else — the most basic template."""

    def test_every_label_gets_a_slot(self):
        assert _slots(_shape("label_value_list")) == {
            "B1", "B2", "B3", "B4", "B5", "B6"}

    def test_each_slot_carries_its_label(self):
        labels = [f["row_label"] for f in _shape("label_value_list")["field_slots"]]
        assert labels == ["Invoice Number", "Invoice Date", "Customer",
                          "Subtotal", "Tax", "Total Due"]

    def test_it_can_extract(self):
        assert is_usable(_shape("label_value_list"))


# ══════════════════════════════════════════════════════════════════════════════
# 2 ── a matrix with two value columns
# ══════════════════════════════════════════════════════════════════════════════

class TestAMatrixWithTwoValueColumns:
    """A1 "Payment Calculation", B1 "Years 1-7", C1 "Years 8-30", labels A2:A5.

    Fixed by R2. Every value column after the first used to be dropped: a slot
    was only ever made immediately right of a STATIC cell and the scan then
    stepped past it, so column C — empty, inside the used range, under its own
    heading — was never considered. Four slots came back where eight were
    drawn, with no error, because `is_usable` was true and nothing held an
    expectation to compare against. Columns now carry a role within a block of
    consecutive rows, and a value column is a slot on every row whose paired
    label holds text.
    """

    def test_the_first_value_column_is_filled(self):
        assert {"B2", "B3", "B4", "B5"} <= _slots(_shape("matrix_two_value_columns"))

    def test_the_second_value_column_is_filled(self):
        assert {"C2", "C3", "C4", "C5"} <= _slots(_shape("matrix_two_value_columns"))

    def test_each_slot_knows_which_column_it_is_in(self):
        by_ref = {f["ref"]: f for f in _shape("matrix_two_value_columns")["field_slots"]}
        assert by_ref["B2"]["col_header"] == "Years 1-7"
        assert by_ref["C2"]["col_header"] == "Years 8-30"


# ══════════════════════════════════════════════════════════════════════════════
# 3 ── a table with a heading row and blank rows
# ══════════════════════════════════════════════════════════════════════════════

class TestATableWithHeaderAndBlankRows:

    def test_it_is_one_band_of_five_columns(self):
        bands = _shape("table_header_blank_rows")["repeat_bands"]
        assert len(bands) == 1
        assert [c["header"] for c in bands[0]["columns"]] == [
            "Date", "Description", "Qty", "Rate", "Amount"]

    def test_the_band_covers_the_rows_that_were_left_blank(self):
        b = _shape("table_header_blank_rows")["repeat_bands"][0]
        assert (b["start_row"], b["end_row"]) == (1, 10)

    def test_the_total_beneath_it_is_a_field_not_a_row(self):
        shape = _shape("table_header_blank_rows")
        assert [f["row_label"] for f in shape["field_slots"]] == ["Total"]


# ══════════════════════════════════════════════════════════════════════════════
# 4 ── a merged section heading above a table
# ══════════════════════════════════════════════════════════════════════════════

class TestAMergedSectionHeading:
    """A heading spanning columns is a title, not a label with a value."""

    def test_the_heading_is_not_a_field(self):
        assert _slots(_shape("merged_section_heading")) == set()

    def test_the_table_takes_the_headings_name(self):
        bands = _shape("merged_section_heading")["repeat_bands"]
        assert [b["name"] for b in bands] == ["QUARTERLY SUMMARY"]

    def test_the_table_keeps_all_five_columns(self):
        b = _shape("merged_section_heading")["repeat_bands"][0]
        assert len(b["columns"]) == 5


# ══════════════════════════════════════════════════════════════════════════════
# 5 ── a Subtotal typed inside the table
# ══════════════════════════════════════════════════════════════════════════════

class TestASubtotalTypedInsideTheTable:
    """Fixed by R3. One typed cell inside a table used to end the band there.

    The extent was "the first row below the header holding ANY static cell,
    minus one", so a Subtotal in A5 yielded a three-row band out of a ten-row
    table while keeping all five columns — the "2 rows and 5 columns with wrong
    values" case — and left `Subtotal` as a stray field competing with the
    table for the same data. A static row now closes a band only when it fills
    at least half the band's columns, or when no blank row follows it before
    the span ends.
    """

    def test_it_is_still_one_band_of_five_columns(self):
        bands = _shape("subtotal_inside_table")["repeat_bands"]
        assert len(bands) == 1
        assert len(bands[0]["columns"]) == 5

    def test_the_band_is_not_truncated_at_the_subtotal(self):
        b = _shape("subtotal_inside_table")["repeat_bands"][0]
        assert b["end_row"] - b["start_row"] + 1 >= 9, (
            f"band covers rows {b['start_row']}-{b['end_row']}")

    def test_the_subtotal_does_not_become_a_stray_field(self):
        labels = [f["row_label"] for f in _shape("subtotal_inside_table")["field_slots"]]
        assert labels == ["Total"], labels
