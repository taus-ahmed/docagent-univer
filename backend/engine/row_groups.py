"""Grouped table rows: a group line above its rows, a subtotal below (Run R, R1).

A vendor invoice list prints

    410022 HOLLOWAY PARTS                   <- the group line
    0031 03/14/2026 R031426 ... 75.00 ...   <- the group's rows
    CHECK DATE: 06/24/2026                  <- a per-row note (furniture)
    388211 NORTHFIELD SUPPLY
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
    if not money and len(toks) >= 2 \
            and any(re.search(r"[A-Za-z]{2}", t) for t in toks) \
            and (":" not in _text(line) or _labelled_group_line(_text(line))):
        return "label"
    return "other"


# ── a group line's parts (Run S, Stage 1b) ───────────────────────────────────
#
# A group line is an identifier and a name ("410022 HOLLOWAY PARTS",
# "Customer Code: KX-77 Harbor Foods", "EMP0042 Jane Q. Doe"). The two are
# separate facts and the sheet gives each its own column. Everything below is
# shape, never vocabulary: an identifier is a token holding a digit; a printed
# label is the words before a colon.

INFERRED_NAME = ("the page prints no label for this column; the engine named it "
                 "from the page's context - please check the name")

_IDENT = re.compile(r"^(?=\S*\d)[A-Za-z0-9][A-Za-z0-9\-/.#]*$")
_LABEL_COLON = re.compile(r"^([A-Za-z][A-Za-z .#/&'-]{0,30}?)\s*:\s*(\S.*)$")
_TITLE_WORD = re.compile(r"^[A-Z][a-z]+$")


def _is_ident(tok) -> bool:
    t = str(tok or "")
    return bool(_IDENT.match(t)) and amount(t) is None and not re.fullmatch(
        r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", t)


def _labelled_group_line(text) -> bool:
    """`Label: <identifier and/or name>`: a group line carrying its own
    label, not a `CHECK DATE: 06/24/2026` note (whose value holds no word)."""
    m = _LABEL_COLON.match(str(text or "").strip())
    if not m:
        return False
    rest = m.group(2).split()
    # a group line names an entity: a date, a time or a figure after the
    # colon makes it a note or a footer ("Report generated: 06/24/2026 14:36")
    if any(re.fullmatch(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}:\d{2}(:\d{2})?", t)
           or amount(t) is not None for t in rest):
        return False
    return any(re.search(r"[A-Za-z]{2}", t) and not _is_ident(t) for t in rest)


def split_group_label(text) -> dict:
    """{"label", "ident", "name", "name_label"} of one group line; a part the
    line does not print is None."""
    t = re.sub(r"\s+", " ", str(text or "").strip())
    label = name_label = None
    m = _LABEL_COLON.match(t)
    rest = t
    if m:
        label, rest = m.group(1).strip(), m.group(2).strip()
    toks = rest.split()
    ident = None
    if toks and _is_ident(toks[0]):
        ident = toks.pop(0)
    elif label is None and len(toks) >= 3:
        # "Account 4411-2290 RIVERSIDE HOLDINGS": one or two Title-case words
        # printed before the identifier are its label
        for k in (1, 2):
            if len(toks) > k + 1 and _is_ident(toks[k]) and all(
                    _TITLE_WORD.match(w) for w in toks[:k]):
                label, ident = " ".join(toks[:k]), toks[k]
                toks = toks[k + 1:]
                break
    if ident is None and len(toks) >= 2 and _is_ident(toks[-1]) \
            and not _is_ident(toks[0]):
        ident = toks.pop()
    name = " ".join(toks).strip() or None
    if name:
        m2 = _LABEL_COLON.match(name)
        if m2:
            name_label, name = m2.group(1).strip(), m2.group(2).strip() or None
    return {"label": label, "ident": ident, "name": name, "name_label": name_label}


def _majority(values):
    vals = [v for v in values if v]
    if not vals:
        return None
    best = max(set(vals), key=vals.count)
    return best if vals.count(best) * 2 > len(values) else None


def group_columns(groups, all_lines) -> dict:
    """The sheet columns a grouped document's group lines go in:
    {"ident": {"name", "inferred"} or None, "name": {"name", "inferred"}}.

    Named by the page's own label when the group lines print one (the colon
    stripped), else by a neutral name from context (`group_noun`), recorded
    as inferred so the export marks the NAME (never the values) for a look."""
    splits = [split_group_label(g.label) for g in groups.groups]
    n = len(splits)
    has_id = sum(1 for s in splits if s["ident"]) * 2 > n
    label = _majority([s["label"] for s in splits])
    name_label = _majority([s["name_label"] for s in splits])
    if label:
        if has_id:
            ident = {"name": label, "inferred": False}
            name = ({"name": name_label, "inferred": False} if name_label else
                    {"name": f"{label.split()[0]} Name", "inferred": True})
        else:
            ident, name = None, {"name": label, "inferred": False}
        return {"ident": ident, "name": name}
    noun = group_noun(all_lines)
    if has_id:
        return {"ident": {"name": f"{noun} ID", "inferred": True},
                "name": {"name": f"{noun} Name", "inferred": True}}
    return {"ident": None, "name": {"name": noun, "inferred": True}}


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
            if g.line <= i:
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


def add_group_column(inferred, page_lines) -> Optional[list]:
    """No template: draw the group's columns (identifier, name) as the first
    columns of the widest inferred table when the document is grouped.
    Returns their names; the engine-chosen ones are listed on the table as
    `inferred_columns`."""
    from text_layer import flatten_pages
    tables = (inferred or {}).get("tables") or []
    if not tables or not page_lines:
        return None
    lines = flatten_pages(page_lines)
    groups = detect(lines)
    if groups is None:
        return None
    gc = group_columns(groups, lines)
    want = [c for c in (gc["ident"], gc["name"]) if c]
    t = max(tables, key=lambda t: len(t.get("columns") or []))
    cols = list(t.get("columns") or [])
    have = {str(c).casefold() for c in cols}
    add = [c["name"] for c in want if c["name"].casefold() not in have]
    t["columns"] = add + cols
    inf = [c["name"] for c in want if c["inferred"]]
    if inf:
        t["inferred_columns"] = list(dict.fromkeys(list(t.get("inferred_columns") or []) + inf))
    return [c["name"] for c in want]


def _norm(v) -> str:
    return re.sub(r"[\s$,]", "", str(v or ""))


def apply(rows, line_of_row, groups: Groups, group_key, headers, level, low,
          split_keys=None):
    """Fill the group's column(s) on each row from the group line its row sits
    under; build the subtotal rows. Returns (subtotal_rows, flags, notes);
    flags are (ref, value, reason) tuples.

    `split_keys` = (identifier key, name key): the line's two parts go in two
    columns (Run S, 1b). Otherwise `group_key` holds the whole line. Either
    way the PAGE's text is written: a model value that is a part of the line
    (the name alone, job 138) is replaced by it, and a model value the line
    does not print is flagged with both readings, never dropped silently."""
    flags, notes = [], []
    filled = 0
    members = {}
    id_key, name_key = split_keys or (None, None)
    gkeys = [k for k in (group_key, id_key, name_key) if k]

    def put(r, key, val, g):
        nonlocal filled
        if not key or not val:
            return
        cur = str(r.get(key, "") or "").strip()
        same = _norm(cur).casefold() == _norm(val).casefold()
        if cur and not same and _norm(cur).casefold() not in _norm(g.label).casefold():
            flags.append((f"{key}[{g.label}]", cur,
                          f"the model read {cur!r} for {key}, but the group line "
                          f"printed above the row says {g.label!r}; the page's "
                          f"{val!r} was written"))
        if not same:
            filled += 1
        r[key] = val

    for r in rows:
        ln = line_of_row.get(id(r))
        if ln is None:
            continue
        g = groups.of_line(ln)
        if g is None:
            continue
        members.setdefault(id(g), []).append(r)
        if split_keys:
            sp = split_group_label(g.label)
            put(r, id_key, sp["ident"], g)
            put(r, name_key, sp["name"] if id_key else (sp["name"] or g.label), g)
        else:
            put(r, group_key, g.label, g)
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
                if h not in gkeys and _norm(r.get(h)) == _norm(figs[g.position]) \
                        and _norm(r.get(h)):
                    col_votes[h] = col_votes.get(h, 0) + 1
    money_key = max(col_votes, key=col_votes.get) if col_votes else None
    label_key = next((h for h in headers if h not in gkeys and h != money_key), None)
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
        if split_keys:
            sp = split_group_label(g.label)
            if id_key:
                row[id_key] = sp["ident"] or ""
            if name_key:
                row[name_key] = (sp["name"] or "") if id_key else (sp["name"] or g.label)
        else:
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
            flags.append((f"{gkeys[0]}[{g.label}].subtotal", g.subtotal,
                          f"the printed subtotal {g.subtotal} for {g.label} does not "
                          f"equal the sum of its {len(mine)} row(s) in {money_key} "
                          f"({got:,.2f})"))
    group_key = group_key or gkeys[0]
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
