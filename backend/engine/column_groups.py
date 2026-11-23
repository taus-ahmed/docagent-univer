"""Run Q, Q2 — a table printed in side-by-side column groups.

A bank statement prints its checks as `Number Date Amount Number Date Amount
Number Date Amount`, three records per line, and its daily balances as
`Date Amount` x3. Read line by line, each printed line looks like ONE row
and the model returned only the first group: job 56 gave 3 of 8 checks and
7 of 21 daily balances, with no warning.

The heading line says how many groups there are: its words are one short
sequence repeated k >= 2 times. Each group's x-span is read from where its
repetition begins, and every body line below is cut at those x-positions.
A group cell holding an amount is one printed record. Nothing here changes
a value; it counts what the page prints so the pipeline can ask for it and
say when it is still missing.
"""
from __future__ import annotations

import re

_AMOUNT = re.compile(r"^\(?-?\$?\d{1,3}(?:,\d{3})*\.\d{2}\)?\*?$|^\(?-?\$?\d+\.\d{2}\)?\*?$")
_WORD = re.compile(r"[^a-z#$]")


def _norm(t):
    return _WORD.sub("", str(t or "").casefold())


def _text(line):
    return " ".join(str(w.get("text", "")) for w in line)


def heading_period(line):
    """(period, k) when the line's words are one sequence of >= 2 words
    repeated k >= 2 times, else None. Digits disqualify: a heading names."""
    toks = [_norm(w.get("text")) for w in line]
    if len(toks) < 4 or any(not t for t in toks):
        return None
    if any(re.search(r"\d", str(w.get("text", ""))) for w in line):
        return None
    for p in range(2, len(toks) // 2 + 1):
        if len(toks) % p == 0 and all(toks[i] == toks[i % p] for i in range(len(toks))):
            return p, len(toks) // p
    return None


def _is_amount(t):
    return bool(_AMOUNT.match(str(t or "").strip()))


def find_groups(lines):
    """Every grouped table on one page's lines:
    [{"line": i, "heading": str, "title": str, "k": k, "records": [str]}]."""
    out = []
    for i, ln in enumerate(lines or []):
        hp = heading_period(ln)
        if not hp:
            continue
        p, k = hp
        starts = [float(ln[g * p].get("x0", 0)) for g in range(k)]
        tol = 4.0
        records, body_lines = [], []
        for bi, body in enumerate(lines[i + 1:], i + 1):
            cells = [[] for _ in range(k)]
            for w in body:
                x = float(w.get("x0", 0))
                g = max((j for j in range(k) if x >= starts[j] - tol), default=None)
                if g is None:
                    g = 0
                cells[g].append(str(w.get("text", "")))
            got = [c for c in cells if any(_is_amount(t) for t in c)]
            if not got:
                break
            records.extend(" ".join(c) for c in got)
            body_lines.append(bi)
        title = _text(lines[i - 1]) if i > 0 else ""
        out.append({"line": i, "heading": _text(ln), "title": title, "k": k,
                    "records": records, "body": body_lines})
    return out


def prompt_hint(page_lines, nums=None):
    """The instruction added to the prompt when a page prints grouped
    columns; empty (so the prompt is byte-identical) when none does."""
    said = []
    for n, lines in enumerate(page_lines or [], 1):
        for g in find_groups(lines):
            if len(g["records"]) > 0:
                said.append(f'- page {n}: "{g["heading"]}" is ONE table printed in '
                            f'{g["k"]} side-by-side column groups ({len(g["records"])} '
                            f"records). Each group on a printed line is a SEPARATE row: "
                            f"read the first group down, then the second, then the third.")
    if not said:
        return ""
    return ("\n\nSIDE-BY-SIDE COLUMN GROUPS. These headings repeat their columns across "
            "the line. Return every record of every group, not only the first:\n"
            + "\n".join(said))


def is_balance_block(group):
    """A DAILY BALANCE summary: a running balance per date, not a transaction."""
    return bool(re.search(r"\bdaily\s+balance|\bbalance\s+summary",
                          f'{group["title"]} {group["heading"]}', re.I))


_ACCT = re.compile(r"\baccount\s*(?:number|no\.?|#)?\s*:?\s*(\d{4,})\b", re.I)


def main_account(page_lines):
    """The account number printed most often as `Account Number: N`."""
    seen = {}
    for lines in page_lines or []:
        for ln in lines or []:
            for m in _ACCT.finditer(_text(ln)):
                seen[m.group(1)] = seen.get(m.group(1), 0) + 1
    return max(seen, key=seen.get) if len(seen) > 1 else None


def other_account_lines(page_lines):
    """{(page index, line index): account} for every line printed after a
    DIFFERENT account number on its page - job 56's ready-reserve loan
    (Account 3216) inside a checking statement (Account 6547)."""
    main = main_account(page_lines)
    if not main:
        return {}
    out = {}
    for pi, lines in enumerate(page_lines or []):
        other = None
        for li, ln in enumerate(lines or []):
            accts = _ACCT.findall(_text(ln))
            if accts:
                other = next((a for a in accts if a != main), None) if main not in accts or len(accts) > 1 else None
                continue
            if other:
                out[(pi, li)] = other
    return out


def _amt(t):
    d = re.sub(r"[^\d.]", "", str(t or ""))
    try:
        return f"{float(d):.2f}"
    except ValueError:
        return None


def reconcile(page_lines, tables_out, transaction_like):
    """Grouped records whose amount no extracted row carries.

    Returns (missing, balance_rows): `missing` is [(file page index, heading,
    k, total, [record])] for every non-balance group block with a record no
    row holds; `balance_rows` is {table name: [row]} - rows of a
    transaction-like table read from a DAILY BALANCE block's lines."""
    have = set()
    for rows in tables_out.values():
        for r in rows:
            for k, v in r.items():
                if not str(k).startswith("_") and _is_amount(str(v).strip().lstrip("$")):
                    have.add(_amt(v))
    missing, balance_rows = [], {}
    for pi, lines in enumerate(page_lines or []):
        for g in find_groups(lines):
            if not g["records"]:
                continue
            if is_balance_block(g):
                body = {_flat(_text(lines[b])) for b in g["body"]}
                for name, rows in tables_out.items():
                    if name not in transaction_like:
                        continue
                    hit = [r for r in rows if _flat(r.get("_source")) and any(
                        _flat(r.get("_source")) in b or b in _flat(r.get("_source")) for b in body)]
                    if hit:
                        balance_rows.setdefault(name, []).extend(hit)
                continue
            lost = [rec for rec in g["records"]
                    if not any(_amt(t) in have for t in rec.split() if _is_amount(t))]
            if lost:
                missing.append((pi, g["heading"], g["k"], len(g["records"]), lost))
    return missing, balance_rows


def _flat(s):
    return re.sub(r"\s+", "", str(s or "")).casefold()
