"""Run B, B7 - OCR split amounts rejoined for the source inventory only."""
from __future__ import annotations

from tests.contract.run_a_driver import words

import source_inventory as SI  # noqa: E402


def _line(*tokens, gap=6):
    x, out = 40.0, []
    for t in tokens:
        out.append({"text": t, "x0": x, "x1": x + 6 * len(t), "top": 50.0, "bottom": 60.0})
        x += 6 * len(t) + gap
    return out


def test_a_dropped_decimal_point_is_rejoined():
    line, n = SI.ocr_amount_repair(_line("07/25/2019", "$9,428", "99"))
    assert n == 1 and [w["text"] for w in line] == ["07/25/2019", "$9,428.99"]


def test_a_comma_read_as_a_point_is_rejoined():
    line, n = SI.ocr_amount_repair(_line("07/26/2019", "$6.428", "29"))
    assert n == 1 and line[-1]["text"] == "$6,428.29"


def test_nothing_is_joined_without_the_shape_or_across_a_gap():
    for tokens in [("$12.53", "44"), ("4423", "Origins"), ("£4", "66"), ("1077", "12")]:
        assert SI.ocr_amount_repair(_line(*tokens))[1] == 0, tokens
    assert SI.ocr_amount_repair(_line("$9,428", "99", gap=40))[1] == 0


def test_the_repair_runs_on_scanned_pages_only():
    page = [words(1, ["07/03 DEPOSIT $9,428 99", "07/04 DEPOSIT $2,688 81"])]
    for ln in page[0]:              # put the cents right beside the amount
        ln[-1]["x0"] = ln[-2]["x1"] + 4
        ln[-1]["x1"] = ln[-1]["x0"] + 12
    native = SI.build(page, [1], origins={1: "native"})["pages"][1]
    scanned = SI.build(page, [1], origins={1: "ocr"})["pages"][1]
    assert [a["value"] for a in scanned["amounts"]] == ["$9,428.99", "$2,688.81"]
    assert [a["value"] for a in native["amounts"]] == ["$9,428", "$2,688"]
