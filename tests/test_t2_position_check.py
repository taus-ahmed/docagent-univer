"""Run T2, Stage 1: the positional checker measures what it says it does.

Hand-built layouts (cells as both Organized engines write them) scored
against hand-written keys, one failure class per test, so a measure that
counts the wrong thing fails here before it is trusted on the corpus.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import position_check as PC  # noqa: E402

KEY = """# file: x.pdf
# half: dev
## page 1
text: ACME BANK
kv: Account: | 0042
table: Date | Description | Amount
row: 01/02/2026 | COFFEE | 4.50
row: 01/03/2026 | RENT | 900.00
exclude: This statement is a sample.
"""


def _c(row, col, text, kind="value", page=1):
    return {"row": row, "col": col, "text": text, "kind": kind, "word_ids": [f"p{page}w{row}{col}"]}


def _perfect():
    return [_c(0, 0, "ACME BANK", "text"), _c(1, 0, "Account:", "label"), _c(1, 1, "0042"),
            _c(3, 0, "Date", "header"), _c(3, 1, "Description", "header"),
            _c(3, 2, "Amount", "header"),
            _c(4, 0, "01/02/2026"), _c(4, 1, "COFFEE"), _c(4, 2, "4.50"),
            _c(5, 0, "01/03/2026"), _c(5, 1, "RENT"), _c(5, 2, "900.00")]


def _score(cells, key=KEY):
    return PC.score({"pages": [cells]}, PC.parse_key(key))


def test_key_parsing_counts_items_and_continued_adds_none():
    k = PC.parse_key(KEY + "## page 2\ncontinued: Date | Description | Amount\n"
                     "row: 01/04/2026 | FUEL | 30.00\n")
    kinds = [it["kind"] for it in k["pages"][1]]
    assert kinds.count("header") == 3 and kinds.count("exclude") == 1
    p2 = k["pages"][2]
    assert [it["kind"] for it in p2] == ["row_label", "value", "value"]
    assert p2[2]["header"] == "Amount"


def test_perfect_layout_scores_full_marks():
    m = _score(_perfect())
    assert m["right_header"] == m["values"] == m["right_row"] == 7
    assert (m["glued"], m["split"], m["missing"], m["extra"]) == (0, 0, 0, 0)


def test_value_under_the_wrong_header():
    cells = _perfect()
    cells[8] = _c(4, 3, "4.50")        # one column right of Amount: no header above
    m = _score(cells)
    assert m["right_header"] == 6
    assert any(f["status"] == "wrong header" and f["item"] == "4.50" for f in m["fails"])


def test_value_in_the_wrong_row():
    cells = _perfect()
    cells[11] = _c(6, 2, "900.00")
    m = _score(cells)
    assert m["right_row"] == 6
    assert any(f["status"] == "wrong row" and f["item"] == "900.00" for f in m["fails"])


def test_two_printed_items_in_one_cell_are_glued():
    cells = [c for c in _perfect() if c["text"] not in ("COFFEE", "4.50")]
    cells.append(_c(4, 1, "COFFEE 4.50"))
    m = _score(cells)
    assert m["glued"] == 1 and m["glued_items"] == 2 and m["missing"] == 0


def test_a_date_range_is_one_item_not_glue():
    key = "# half: dev\n## page 1\nkv: Period: | 08/01/2026 - 08/31/2026\n"
    m = _score([_c(0, 0, "Period:", "label"), _c(0, 1, "08/01/2026 - 08/31/2026")], key)
    assert m["glued"] == 0 and m["right_header"] == 1


def test_one_item_over_two_cells_is_split():
    cells = [c for c in _perfect() if c["text"] != "ACME BANK"]
    cells += [_c(0, 0, "ACME", "text"), _c(0, 1, "BANK", "text")]
    m = _score(cells)
    assert m["split"] == 1 and m["missing"] == 0 and m["extra"] == 0


def test_missing_extra_and_excluded_text():
    cells = [c for c in _perfect() if c["text"] != "RENT"]
    cells += [_c(9, 0, "This statement is a sample.", "text"), _c(10, 0, "stray", "text")]
    m = _score(cells)
    assert m["missing"] == 1
    assert m["excluded_placed"] == 1 and m["extra"] == 2


def test_a_title_inside_a_footer_sentence_is_not_excluded_text():
    key = "# half: dev\n## page 1\ntext: ACME\nexclude: ACME Bank does not exist. Every name is invented.\n"
    m = _score([_c(0, 0, "ACME", "text")], key)
    assert m["excluded_placed"] == 0 and m["extra"] == 0


def test_kv_value_right_header_means_label_directly_left():
    cells = _perfect()
    cells[2] = _c(2, 0, "0042")                   # under the label, not beside it
    m = _score(cells)
    assert any(f["item"] == "0042" and f["status"] == "wrong header" for f in m["fails"])


def test_stacked_header_is_read_joined():
    key = "# half: dev\n## page 1\ntable: Tran Date Post Date | Amount\nrow: 01/02 | 4.50\n"
    cells = [_c(0, 0, "Tran Date", "header"), _c(1, 0, "Post Date", "header"),
             _c(1, 1, "Amount", "header"), _c(2, 0, "01/02"), _c(2, 1, "4.50")]
    m = _score(cells, key)
    assert m["right_header"] == 2


def test_header_row_the_layout_did_not_mark_still_counts():
    cells = [dict(c, kind="label") if c["kind"] == "header" else c for c in _perfect()]
    m = _score(cells)
    assert m["right_header"] == 7


def test_dollar_sign_apart_from_its_figure_is_the_same_text():
    assert PC.norm("$ 1,000") == PC.norm("$1,000")
    assert PC.norm("Employer Name:") == PC.norm("Employer Name")


def test_every_committed_key_parses_and_names_its_half():
    keys = PC.load_keys()
    assert len(keys) == 11
    halves = {k["half"] for k in keys}
    assert halves == {"dev", "heldout"}
    for k in keys:
        assert k["file"] and k["pages"], k["name"]
        assert sum(len(v) for v in k["pages"].values()) >= 10, k["name"]
