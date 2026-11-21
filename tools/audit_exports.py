"""Read-only scoreboard for a folder of exported workbooks (Run Q, Q15).

    backend\\.venv\\Scripts\\python.exe tools\\audit_exports.py local_docs\\rounds
    backend\\.venv\\Scripts\\python.exe tools\\audit_exports.py local_docs\\batch1_exports --json out.json

Opens every .xlsx under the folder (recursively), never writes to it, and
reports per file:

  low        cells filled red (Low: a check failed)
  amber      cells filled amber (unverified / needs review)
  grey       cells filled grey (empty, flagged)
  accepted   cells a person accepted after they were flagged Low
             (pale green, comment "Machine status was Low")
  placeholder  cell values that are dummy text (XX,XXX.00, 9999.99, 00/00/00,
             20XX, "YOUR CITY", "<...>", "City, State, Zip", ...) -- the Q6 list
  money_text money-looking values stored as TEXT ("$2,750", "(1,300)")
  legend_off Legend counts that disagree with the marked cells
             (Legend "Low" vs red cells; Legend "Need review" vs red+amber+grey)
  sum_off    a "Total"/"Subtotal" row whose number disagrees with the sum of the
             numbers directly above it in the same column (heuristic; >=2 items)
  count_off  a printed count ("Number of Checks", "Total Invoices Count", ...)
             that disagrees with the row count of the table below/near it
             (heuristic: the longest run of consecutive filled rows)

Offline only; no network, no database, no model.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

FILL = {"FFFFC7CE": "low", "FFFFEB9C": "amber", "FFD9D9D9": "grey",
        "FFE2EFDA": "reviewed", "FFE4DFEC": "edited"}

PLACEHOLDER = re.compile(
    r"^(?:\$?\s*X{1,3}(?:,X{3})*\.(?:XX|00)"          # XX,XXX.00 / $X,XXX.XX (a bare X is a tick)
    r"|\$?\s*X{1,3}(?:,X{3})+"
    r"|\$?\s*9{4,}(?:\.9{2})?"                          # 9999.99 / 99999999.99
    r"|00/00/(?:00|0000)"
    r"|(?:19|20)XX"
    r"|<[^<>]{1,60}>"                                   # <Company Name>
    r"|YOUR\b.*"                                        # YOUR CITY, YOUR STATE, ZIP
    r"|CITY,?\s*STATE,?\s*ZIP(?:\s*CODE)?"
    r"|DESIGNATION\s*\(IF ANY\)"
    r"|_{3,}"
    r")$", re.I)

MONEY_TEXT = re.compile(r"^\(?\s*-?\s*[$£€]?\s*\(?\s*-?\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?\s*\)?$"
                        r"|^\(?\s*-?\s*[$£€]\s*\d+(?:\.\d{1,2})?\s*\)?$"
                        r"|^\(\s*\d+(?:\.\d{2})?\s*\)$")

COUNT_LABEL = re.compile(r"\b(?:number|count|no\.?|#)\s+of\s+(?:checks|invoices|items|"
                         r"transactions|deposits|withdrawals)\b|\btotal\s+\w*\s*count\b"
                         r"|\b(?:invoices|checks|items)\s+count\b", re.I)
TOTAL_LABEL = re.compile(r"^\s*(?:sub\s*-?\s*total|total)\b", re.I)


def _num(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("$", "").replace(" ", "")
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()")
        try:
            f = float(s)
        except ValueError:
            return None
        return -f if neg else f
    return None


def _fill(c):
    try:
        if c.fill is None or c.fill.fill_type != "solid":
            return None
        rgb = c.fill.fgColor.rgb
        return FILL.get(str(rgb).upper()) if isinstance(rgb, str) else None
    except AttributeError:
        return None


def _legend(wb):
    if "Legend" not in wb.sheetnames:
        return None
    rows = list(wb["Legend"].iter_rows(values_only=True))
    try:
        i = next(k for k, r in enumerate(rows) if r and r[0] == "Document")
    except StopIteration:
        return None
    head = [str(h or "") for h in rows[i]]
    tot = {"need": 0, "low": 0, "grey": 0, "docs": 0}
    for r in rows[i + 1:]:
        if not r or r[0] is None or not isinstance(r[1], (int, float)):
            break
        d = dict(zip(head, r))
        tot["docs"] += 1
        tot["need"] += int(d.get("Need review") or 0)
        tot["low"] += int(d.get("Low") or 0)
        tot["grey"] += int(d.get("Empty, flagged") or 0)
    return tot


def _sheet_checks(ws):
    grid = {}
    for row in ws.iter_rows():
        for c in row:
            if c.value not in (None, ""):
                grid[(c.row, c.column)] = c.value
    sum_off, count_off = [], []
    max_r = ws.max_row
    for (r, col), v in list(grid.items()):
        if not isinstance(v, str):
            continue
        if TOTAL_LABEL.match(v):
            for c2 in range(col + 1, ws.max_column + 1):
                tv = _num(grid.get((r, c2)))
                if tv is None:
                    continue
                items, rr = [], r - 1
                while rr >= 1 and _num(grid.get((rr, c2))) is not None \
                        and not (isinstance(grid.get((rr, col)), str) and TOTAL_LABEL.match(grid[(rr, col)])):
                    items.append(_num(grid[(rr, c2)]))
                    rr -= 1
                if len(items) >= 2 and abs(sum(items) - tv) > 0.005:
                    sum_off.append(f"{ws.title}!R{r}C{c2} '{v}' {tv:g} vs sum of {len(items)} above "
                                   f"{sum(items):.2f}")
                break
        if COUNT_LABEL.search(v):
            cv = None
            for c2 in range(col + 1, min(col + 4, ws.max_column + 1)):
                cv = _num(grid.get((r, c2)))
                if cv is not None:
                    break
            if cv is None or cv != int(cv) or cv < 1:
                continue
            best, run = 0, 0
            for rr in range(1, max_r + 1):
                filled = sum(1 for cc in range(1, ws.max_column + 1) if (rr, cc) in grid)
                run = run + 1 if filled >= 2 else 0
                best = max(best, run)
            # the run includes its own heading line
            if best and abs((best - 1) - cv) > 0 and abs(best - cv) > 0:
                count_off.append(f"{ws.title}!R{r} '{v}' prints {int(cv)}, longest table holds "
                                 f"{best - 1} rows")
    return sum_off, count_off


def audit_file(path: Path) -> dict:
    import openpyxl
    wb = openpyxl.load_workbook(path)
    out = {"file": path.name, "low": 0, "amber": 0, "grey": 0, "accepted": 0,
           "placeholder": 0, "money_text": 0, "legend_off": [], "sum_off": [],
           "count_off": [], "examples": {"placeholder": [], "money_text": []}}
    for ws in wb.worksheets:
        if ws.title == "Legend":
            continue
        for row in ws.iter_rows():
            for c in row:
                f = _fill(c)
                if f in ("low", "amber", "grey"):
                    out[f] += 1
                if f == "reviewed" and c.comment is not None and \
                        "machine status was low" in (c.comment.text or "").lower():
                    out["accepted"] += 1
                v = c.value
                if isinstance(v, str) and v.strip():
                    s = v.strip()
                    if PLACEHOLDER.match(s):
                        out["placeholder"] += 1
                        out["examples"]["placeholder"].append(s[:40])
                    elif MONEY_TEXT.match(s):
                        out["money_text"] += 1
                        out["examples"]["money_text"].append(s[:40])
        s_off, c_off = _sheet_checks(ws)
        out["sum_off"] += s_off
        out["count_off"] += c_off
    lg = _legend(wb)
    if lg is not None:
        if lg["low"] != out["low"]:
            out["legend_off"].append(f"Legend Low {lg['low']} vs {out['low']} red cells")
        marked = out["low"] + out["amber"] + out["grey"]
        if lg["need"] != marked:
            out["legend_off"].append(f"Legend Need review {lg['need']} vs {marked} marked cells")
    for k in out["examples"]:
        out["examples"][k] = sorted(set(out["examples"][k]))[:6]
    return out


def audit(folder: Path) -> list:
    files = sorted(p for p in Path(folder).rglob("*.xlsx") if not p.name.startswith("~$"))
    return [audit_file(p) for p in files]


COLS = ("low", "amber", "grey", "accepted", "placeholder", "money_text")


def render(rows) -> str:
    head = f"{'file':34} " + " ".join(f"{c[:8]:>8}" for c in COLS) + "  legend sum count"
    lines = [head]
    tot = {c: 0 for c in COLS}
    off = {"legend_off": 0, "sum_off": 0, "count_off": 0}
    for r in rows:
        for c in COLS:
            tot[c] += r[c]
        for k in off:
            off[k] += len(r[k])
        lines.append(f"{r['file'][:34]:34} " + " ".join(f"{r[c]:>8}" for c in COLS)
                     + f"  {len(r['legend_off']):>6} {len(r['sum_off']):>3} {len(r['count_off']):>5}")
    lines.append(f"{'TOTAL (' + str(len(rows)) + ' files)':34} " + " ".join(f"{tot[c]:>8}" for c in COLS)
                 + f"  {off['legend_off']:>6} {off['sum_off']:>3} {off['count_off']:>5}")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folders", nargs="+")
    ap.add_argument("--json", help="also write the full findings here")
    ap.add_argument("--details", action="store_true", help="print each finding")
    a = ap.parse_args(argv)
    rows = []
    for f in a.folders:
        rows += audit(Path(f))
    print(render(rows))
    if a.details:
        for r in rows:
            for k in ("legend_off", "sum_off", "count_off"):
                for x in r[k]:
                    print(f"  {r['file']}: {k}: {x}")
            for k, ex in r["examples"].items():
                if ex:
                    print(f"  {r['file']}: {k}: {ex}")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
