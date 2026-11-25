"""Grouped table rows: a group line above its rows, a subtotal below (Run R, R1).

A vendor invoice list prints

    300055 ANDERSON DULANEY                 <- the group line
    0025 06/22/2026 H062426 ... 75.00 ...   <- the group's rows
    CHECK DATE: 06/24/2026                  <- a per-row note (furniture)
    299694 B&B LAWN/LANDSCAPING
    2937 ... 2,480.00 ...
    2938 ... 2,400.00 ...
    4,880.00                                <- the group's subtotal

and the table's rows carry neither the vendor nor the subtotal, so an export
of the rows alone loses who each invoice was paid to (job 131: 31 vendor lines,
14 subtotals, none in the sheet).

Everything here is read off the text layer, deterministically, and decided
by ARITHMETIC: a document is grouped only when at least one bare amount line
equals the sum of one money position over the rows above it since the last
group line. A list of addresses above a table, or a page of label lines,
never reconciles, so it is never read as groups.

    detect(all_lines)            -> Groups or None
    group_noun(all_lines)        -> "Vendor" / "Supplier" / ... / "Group"
    add_group_column(inferred, page_lines)   no-template: the column is drawn
    apply(rows, line_of_row, groups, group_key, money_keys, level)
                                 -> (subtotal rows, flags, notes)

Subtotal rows are NOT table rows: every row check, count and sum in the
engine reads `<band>_rows`, and a subtotal there would be counted twice.
They travel as `<band>_subtotals` and only the writer interleaves them
(`rows_with_subtotals`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import List, Optional

_MONEY = re.compile(r"^\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?-?$")
_NOUNS = ("vendor", "supplier", "payee", "customer", "employee", "client",
          "member", "account", "department")


def _text(line) -> str:
    return " ".join(str(w.get("text", "")) for w in (line or []))


def _toks(line):
    return [str(w.get("text", "")) for w in (line or [])]


def _page(line):
    for w in line or ():
        if isinstance(w, dict) and w.get("page") is not None:
            return int(w["page"])
    return None


def amount(tok) -> Optional[Decimal]:
    t = str(tok or "").strip()
    if not _MONEY.match(t):
        return None
    neg = t.startswith("(") or t.startswith("-") or t.endswith("-")
    try:
        v = Decimal(re.sub(r"[^\d.]", "", t))
    except InvalidOperation:
        return None
    return -v if neg else v


def _kind(line) -> str:
    toks = _toks(line)
    if not toks:
        return "blank"
    money = [t for t in toks if amount(t) is not None]
    if money and len(money) == len(toks) and len(toks) <= 3:
        return "amount"
    if money and len(toks) >= 4:
        return "row"
    if not money and ":" not in _text(line) and len(toks) >= 2 \
            and any(re.search(r"[A-Za-z]{2}", t) for t in toks):
        return "label"
    return "other"


@dataclass
class Group:
    label: str
    line: int                       # index of the group line in all_lines
    rows: List[int] = field(default_factory=list)
    subtotal: Optional[str] = None  # the printed text
    subtotal_line: Optional[int] = None
    position: Optional[int] = None  # money position the subtotal sums


@dataclass
class Groups:
    groups: List[Group]
    position: Optional[int]          # the money position subtotals reconcile on
    grand_total: Optional[str] = None
    grand_line: Optional[int] = None
    lines: list = field(default_factory=list, repr=False)

    def of_line(self, i):
        """The group whose span holds line `i`: after its group line, before
        the next group line, and not past its own subtotal. None otherwise."""
        best = None
        for g in self.groups:
            if g.line < i:
                best = g
            else:
                break
        if best is not None and best.subtotal_line is not None                 and i > best.subtotal_line:
            return None
        return best


def _furniture(all_lines) -> set:
    """Lines printed identically on two or more pages (titles, headings)."""
    seen = {}
    for ln in all_lines:
        seen.setdefault(_text(ln).strip(), set()).add(_page(ln))
    return {t for t, pages in seen.items() if len(pages) >= 2}


def _sums(lines_idx, all_lines):
    """{money position: sum} over the row lines `lines_idx`."""
    out = {}
    for i in lines_idx:
        vals = [amount(t) for t in _toks(all_lines[i])]
        vals = [v for v in vals if v is not None]
        for k, v in enumerate(vals):
            out[k] = out.get(k, Decimal(0)) + v
    return out


def detect(all_lines) -> Optional[Groups]:
    if not all_lines:
        return None
    furn = _furniture(all_lines)
    groups: List[Group] = []
    cur = None
    for i, ln in enumerate(all_lines):
        k = _kind(ln)
        txt = _text(ln).strip()
        if k == "label" and txt not in furn:
            # the group's first row follows - on the next page too, past the
            # footer and the repeated title and headings (job 131 page 3/4)
            nxt = None
            for j in range(i + 1, min(i + 10, len(all_lines))):
                cand = all_lines[j]
                ct = _text(cand).strip()
                if ct in furn or (_kind(cand) == "other" and ":" in ct):
                    continue
                nxt = cand
                break
            if nxt is not None and _kind(nxt) == "row":
                cur = Group(label=txt, line=i)
                groups.append(cur)
                continue
        if cur is None:
            continue
        if k == "row":
            if cur.subtotal is None:
                cur.rows.append(i)
        elif k == "amount" and cur.rows and cur.subtotal is None:
            cur.subtotal, cur.subtotal_line = txt, i
    if len(groups) < 2:
        return None
    votes = {}
    for g in groups:
        if g.subtotal is None:
            continue
        s = amount(g.subtotal.split()[-1])
        for pos, tot in _sums(g.rows, all_lines).items():
            if tot == s:
                g.position = pos
                votes[pos] = votes.get(pos, 0) + 1
                break
    if sum(votes.values()) < 2:
        # nothing (or one coincidence) reconciles: not a grouped table. One
        # was not enough - a Closing Disclosure has exactly one bare amount
        # that happens to sum the lines above it
        return None
    out = Groups(groups=groups, position=max(votes, key=votes.get), lines=all_lines)
    # the printed grand total: the last money figure on a non-row line after
    # the last group's rows ("90 INVOICES 237,183.08", "Grand Total 1,234.00")
    last = max((g.subtotal_line or (g.rows[-1] if g.rows else g.line))
               for g in groups)
    for i in range(last + 1, len(all_lines)):
        ln = all_lines[i]
        if _kind(ln) in ("other", "amount"):
            figs = [t for t in _toks(ln) if amount(t) is not None]
            if figs and (re.search(r"total|\binvoices?\b|\bitems?\b", _text(ln), re.I)
                         or _kind(ln) == "amount"):
                out.grand_total, out.grand_line = figs[-1], i
                break
    return out


def group_noun(all_lines) -> str:
    for ln in all_lines[:12]:
        low = _text(ln).casefold()
        for n in _NOUNS:
            if re.search(rf"\b{n}\b", low):
                return n.capitalize()
    return "Group"


def add_group_column(inferred, page_lines) -> Optional[str]:
    """No template: draw the group column as the first column of the widest
    inferred table when the document is grouped. Returns the column's name."""
    from text_layer import flatten_pages
    tables = (inferred or {}).get("tables") or []
    if not tables or not page_lines:
        return None
    lines = flatten_pages(page_lines)
    if detect(lines) is None:
        return None
    noun = group_noun(lines)
    t = max(tables, key=lambda t: len(t.get("columns") or []))
    cols = t.get("columns") or []
    if any(str(c).casefold() == noun.casefold() for c in cols):
        return noun
    t["columns"] = [noun] + list(cols)
    return noun


def _norm(v) -> str:
    return re.sub(r"[\s$,]", "", str(v or ""))


def apply(rows, line_of_row, groups: Groups, group_key, headers, level, low):
    """Fill `group_key` on each row from the group its line sits in; build the
    subtotal rows. Returns (subtotal_rows, flags, notes); flags are
    (ref, value, reason) tuples."""
    flags, notes = [], []
    filled = 0
    members = {}
    for r in rows:
        ln = line_of_row.get(id(r))
        if ln is None:
            continue
        g = groups.of_line(ln)
        if g is None:
            continue
        members.setdefault(id(g), []).append(r)
        if not str(r.get(group_key, "") or "").strip():
            r[group_key] = g.label
            filled += 1
    # which band column the reconciling money position is: the column whose
    # value equals that position's printed figure on every member row
    col_votes = {}
    for g in groups.groups:
        if g.position is None:
            continue
        for r in members.get(id(g), []):
            ln = line_of_row.get(id(r))
            figs = [t for t in _toks(groups.lines[ln]) if amount(t) is not None]
            if g.position >= len(figs):
                continue
            for h in headers:
                if h != group_key and _norm(r.get(h)) == _norm(figs[g.position]) \
                        and _norm(r.get(h)):
                    col_votes[h] = col_votes.get(h, 0) + 1
    money_key = max(col_votes, key=col_votes.get) if col_votes else None
    label_key = next((h for h in headers if h != group_key and h != money_key), None)
    subtotals = []
    reconciled = mism = 0
    for g in groups.groups:
        if g.subtotal is None:
            continue
        mine = members.get(id(g), [])
        if money_key is None or not mine:
            continue
        s = amount(g.subtotal.split()[-1])
        got = sum((amount(_norm(r.get(money_key))) or Decimal(0) for r in mine),
                  Decimal(0))
        ok = got == s
        row = {h: "" for h in headers}
        row[group_key] = g.label
        if label_key:
            row[label_key] = "Subtotal"
        row[money_key] = g.subtotal
        row["_subtotal"] = True
        row["_confidence"] = level if ok else low
        row["_source"] = g.subtotal
        row["_page"] = _page(groups.lines[g.subtotal_line])
        subtotals.append(row)
        if ok:
            reconciled += 1
        else:
            mism += 1
            row["_ungrounded"] = [money_key]
            flags.append((f"{group_key}[{g.label}].subtotal", g.subtotal,
                          f"the printed subtotal {g.subtotal} for {g.label} does not "
                          f"equal the sum of its {len(mine)} row(s) in {money_key} "
                          f"({got:,.2f})"))
    if filled:
        notes.append(f"{group_key}: filled on {filled} row(s) from the group line "
                     f"printed above them ({len(groups.groups)} groups)")
    if subtotals:
        notes.append(f"{group_key}: {len(subtotals)} printed subtotal(s) kept as "
                     f"subtotal rows; {reconciled} equal the sum of their rows"
                     + (f", {mism} do not" if mism else ""))
    if groups.grand_total and money_key:
        total = sum((amount(_norm(r.get(money_key))) or Decimal(0) for r in rows),
                    Decimal(0))
        g = amount(groups.grand_total)
        if g is not None and g == total:
            notes.append(f"{group_key}: the printed grand total {groups.grand_total} "
                         f"equals the sum of all {len(rows)} rows in {money_key}")
        elif g is not None:
            flags.append((f"{group_key}.grand total", groups.grand_total,
                          f"the printed grand total {groups.grand_total} does not "
                          f"equal the sum of the {len(rows)} rows in {money_key} "
                          f"({total:,.2f})"))
    return subtotals, flags, notes


def rows_with_subtotals(ed, name):
    """The rows the writer writes: each subtotal after the last row of its
    group. A subtotal whose group has no row is left out."""
    rows = list(ed.get(f"{name}_rows") or [])
    subs = ed.get(f"{name}_subtotals") or []
    if not subs:
        return rows
    key = ed.get(f"{name}_group_key")
    out = list(rows)
    for s in subs:
        lab = s.get(key) if key else None
        last = max((i for i, r in enumerate(out)
                    if not r.get("_subtotal") and key and r.get(key) == lab),
                   default=None)
        if last is None:
            continue
        j = last + 1
        while j < len(out) and out[j].get("_subtotal"):
            j += 1
        out.insert(j, s)
    return out
