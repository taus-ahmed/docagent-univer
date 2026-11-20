"""B4 (overnight): does an exported workbook's Legend agree with its cells?

The Legend's second line states "N low · N unverified · N empty and flagged
· N values in all" and its headline "N values need review". Every one of
those values is a marked cell on a results sheet: red = low, grey = empty and
flagged, amber = unverified or otherwise owing a look. `check(wb)` returns
the counts both ways and the mismatches; [] means they agree.

Usable as a script over a folder of exports:
    python -m tests.legend_check local_docs/batch1_exports
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

RED, AMBER, GREY = "FFFFC7CE", "FFFFEB9C", "FFD9D9D9"


def legend_counts(wb) -> dict:
    lg = wb["Legend"]
    out = {"needs_review": 0}
    for r in range(1, 6):
        t = str(lg.cell(r, 1).value or "")
        m = re.search(r"(\d+) low · (\d+) unverified · (\d+) empty and flagged", t)
        if m:
            out.update(low=int(m.group(1)), unverified=int(m.group(2)),
                       empty_flagged=int(m.group(3)))
        m = re.match(r"(\d+) values? needs? review", t)
        if m:
            out["needs_review"] = int(m.group(1))
    return out


def cell_counts(wb) -> dict:
    out = {"red": 0, "amber": 0, "grey": 0}
    for ws in wb.worksheets:
        if ws.title in ("Legend", "Categories", "Anomalies", "Charts"):
            continue
        for row in ws.iter_rows():
            for c in row:
                if not (c.fill and c.fill.fill_type == "solid"):
                    continue
                rgb = c.fill.fgColor.rgb
                # a marked VALUE carries a comment; a header strip does not
                if not c.comment:
                    continue
                if rgb == RED:
                    out["red"] += 1
                elif rgb == AMBER:
                    out["amber"] += 1
                elif rgb == GREY:
                    out["grey"] += 1
    return out


def check(wb) -> list:
    lg, cells = legend_counts(wb), cell_counts(wb)
    bad = []
    if lg.get("low") != cells["red"]:
        bad.append(f"Legend says {lg.get('low')} low, sheet has {cells['red']} red cells")
    if lg.get("empty_flagged") != cells["grey"]:
        bad.append(f"Legend says {lg.get('empty_flagged')} empty and flagged, sheet has "
                   f"{cells['grey']} grey cells")
    marked = cells["red"] + cells["amber"] + cells["grey"]
    if lg.get("needs_review", 0) != marked:
        bad.append(f"Legend says {lg.get('needs_review', 0)} need review, sheet marks "
                   f"{marked} cells")
    return bad


def main(folder):
    import openpyxl
    total = 0
    for p in sorted(Path(folder).glob("*.xlsx")):
        bad = check(openpyxl.load_workbook(p))
        total += bool(bad)
        print(f"{p.name}: {'OK' if not bad else '; '.join(bad)}")
    print(f"{total} workbook(s) disagree")


if __name__ == "__main__":
    main(sys.argv[1])
