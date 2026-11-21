"""Which slot a printed value BELONGS to (overnight run, A1/A2).

Grounding proves a string is on the page; it cannot say the string answers
THIS slot. Three shapes of that failure were found in the real staging
exports, and each has a geometric answer:

1. A FORM BOX (``Box 11 …``) answered with a value printed in a different box.
   Job 51 (pitt_sample_w2): Box 11 Nonqualified Plans took ``4107.00``, which
   is printed under ``12a See instructions for box 12``; Box 11 is blank.
   A box's value sits right of or below its own printed box code, so the
   OWNER of a printed word is the nearest box code above-or-left of it
   (``box_owner``). A value every printed occurrence of which is owned by a
   different box is not this slot's value: it is CLEARED (with a note) —
   the slot is blank on the page, so it stays plainly empty.

2. A CHECKBOX group (``Box 13 Statutory Employee / Retirement Plan /
   Third-Party Sick Pay``). Every option quotes the same ``X``, so grounding
   confirms whichever is picked. An X belongs to the option whose printed
   heading it sits under, by x-position (``checkbox_marks``).

3. The SAME value in two slots whose labels are not aliases, where only one
   of them is witnessed. Job 42: ``Remit To Bank`` took the vendor's name from
   the payment sentence; no bank is printed. A slot is witnessed when a word
   of its own label is printed on its quote's line or the line above it, or
   when its quote is the value alone (a name printed on its own line). The
   unwitnessed copy embedded in a longer line is cleared with a note.

A table row whose amounts are owned by a different box than its table's
(``Box 12 Codes`` answered with Box 14's ``52.00``) is never placed in the
band (``foreign_box_rows``).

Every rule abstains when the geometry is missing or ambiguous: no verdict is
ever drawn from a guess.
"""
from __future__ import annotations

import re

#: a printed box code: `11`, `12a`, `14Other`, `12aSeeinstructions…`, `d`, `e/f`
_CODE_GLUED = re.compile(r"^(\d{1,2}[a-d]?)(?=[A-Z])")
_CODE_ALONE = re.compile(r"^(\d{1,2}[a-d]?|[a-f](?:/[a-f])?)$")
_SLOT_BOX = re.compile(r"^\s*box\s+(\d{1,2}[a-d]?|[a-f](?:/[a-f])?)\b", re.I)
_MARK = {"x", "✓", "✔", "☒", "[x]"}
_GENERIC = {"name", "number", "amount", "address", "date", "total", "code",
            "type", "other", "box", "the", "and", "for", "with", "from",
            "account", "details", "information", "value", "line"}


def slot_box(label) -> str:
    """The box code a slot label names (`Box 11 Nonqualified Plans` -> `11`)."""
    m = _SLOT_BOX.match(str(label or ""))
    return m.group(1).lower() if m else ""


def _num(code: str) -> str:
    m = re.match(r"\d+", code or "")
    return m.group(0) if m else (code or "")


def same_box(a: str, b: str) -> bool:
    """`12` owns `12a`; `e/f` owns `e` and `f`; letters compare whole."""
    if not a or not b:
        return False
    if a[0].isdigit() and b[0].isdigit():
        return _num(a) == _num(b)
    return bool(set(a.split("/")) & set(b.split("/")))


def _f(w, k, d=0.0):
    try:
        return float(w.get(k, d))
    except (TypeError, ValueError):
        return d


def _codes_on(line):
    """[(code, word)] for the box codes printed on one line."""
    ws = [w for w in line if str(w.get("text", "")).strip()]
    out = []
    for i, w in enumerate(ws):
        t = str(w.get("text", ""))
        m = _CODE_GLUED.match(t)
        if m:
            out.append((m.group(1).lower(), w))
            continue
        m = _CODE_ALONE.match(t)
        if m and i + 1 < len(ws):
            nxt = str(ws[i + 1].get("text", ""))
            # a code is followed by its caption (a word starting with a letter),
            # never by a figure — `2 Federal…` is a code, `2 320.00` is not
            if re.match(r"[A-Za-z’']", nxt) and _f(ws[i + 1], "x0") - _f(w, "x1") < 12:
                out.append((m.group(1).lower(), w))
    return out


def box_owner(word, lines, max_dy=40.0):
    """The box code a printed word sits in: the nearest code above-or-left of
    it on the same page (smallest vertical distance, then the nearest
    horizontally). None when no code qualifies."""
    page = word.get("page")
    x0, top = _f(word, "x0"), _f(word, "top")
    best = None
    for ln in lines:
        if not ln or (page is not None and ln[0].get("page") not in (None, page)):
            continue
        for code, w in _codes_on(ln):
            if w is word:
                continue
            wx, wt = _f(w, "x0"), _f(w, "top")
            dy = top - wt
            if wx > x0 + 2 or dy < -3 or dy > max_dy:
                continue
            key = (round(max(dy, 0) / 4), -wx)
            if best is None or key < best[0]:
                best = (key, code)
    return best[1] if best else None


def _key(s: str) -> str:
    s = str(s or "").strip()
    n = re.sub(r"[,$£€\s]", "", s)
    if re.fullmatch(r"\(?-?\d+(\.\d+)?\)?-?", n):
        try:
            return "#" + format(float(n.strip("()-")), ".2f")
        except ValueError:
            pass
    return re.sub(r"\s+", " ", s).casefold()


def occurrences(value, lines):
    """Every printed word (single-word values) equal to `value`."""
    k = _key(value)
    if not k or " " in str(value).strip():
        return []
    return [w for ln in lines for w in ln
            if str(w.get("text", "")).strip() and _key(w.get("text")) == k]


def foreign_value(value, slot_label, lines, source="") -> str:
    """The box that owns EVERY printed occurrence of `value`, when that box is
    not the slot's own; '' otherwise (own box found, or no verdict).

    When the model's quote is found on a line holding the value, only the
    occurrences on THAT line are judged — the copy it read. A form printed in
    several copies (a W-2's B/C/2 copies) can shred a box code in one copy,
    and a shredded copy must not outvote the one that was read."""
    own = slot_box(slot_label)
    if not own:
        return ""
    occ = occurrences(value, lines)
    i = _line_index(source, lines)
    if i is not None:
        mine = [w for w in occ if any(w is x for x in lines[i])]
        if mine:
            occ = mine
    if not occ:
        return ""
    owners = [box_owner(w, lines) for w in occ]
    if any(o is None or same_box(own, o) for o in owners):
        return ""
    return owners[0]


# ── checkboxes ──────────────────────────────────────────────────────────────

def _is_mark(v) -> bool:
    return str(v or "").strip().casefold() in _MARK


def _option_stem(label: str) -> str:
    rest = _SLOT_BOX.sub("", str(label or "")).strip()
    w = re.sub(r"[^a-z0-9]+", " ", rest.casefold()).split()
    if not w:
        return ""
    first = w[0]
    return "3rd" if first in ("third", "3rd") else first[:3]


def _segments(line, start_x):
    """Sub-captions of a caption line right of x, split where a glued caption
    changes word (`Statemp.Ret.plan` -> `Statemp.` / `Ret.plan`), with
    x-spans apportioned by character count."""
    out = []
    for w in line:
        t = str(w.get("text", ""))
        x0, x1 = _f(w, "x0"), _f(w, "x1")
        if x0 < start_x - 1 or not t:
            continue
        parts = [p for p in re.split(r"(?<=\.)(?=[A-Z0-9])|(?<=[a-z])(?=[A-Z])", t) if p]
        n = sum(len(p) for p in parts) or 1
        cx = x0
        for p in parts:
            px = (x1 - x0) * len(p) / n
            out.append((p.casefold(), cx, cx + px))
            cx += px
    return out


#: Run N, N4: an X whose distance to two options differs by no more than this
#: (points) sits between them — geometry does not decide.
TIE_PT = 0.5


def checkbox_marks(group, lines):
    """{slot ref: True|False|None} for a group of checkbox slots sharing one
    box, or {} when the page gives no verdict. `group` is [(slot, value)].
    None: an X sits equally between this option and another (Run N, N4)."""
    code = slot_box(group[0][0]["row_label"])
    for ln in lines:
        for c, w in _codes_on(ln):
            if c != code:
                continue
            segs = _segments(ln, _f(w, "x1"))
            stems = {s["ref"]: _option_stem(s["row_label"]) for s, _v in group}
            spans = {}
            for ref, stem in stems.items():
                hit = [sg for sg in segs if stem and sg[0].startswith(stem)]
                if len(hit) != 1:
                    return {}
                spans[ref] = hit[0][1:]
            top = _f(w, "top")
            marks = [m for l2 in lines for m in l2
                     if m.get("page") == w.get("page") and _is_mark(m.get("text"))
                     and 0 < _f(m, "top") - top <= 20]
            if not marks:
                return {ref: False for ref in spans}
            out = {ref: False for ref in spans}
            for m in marks:
                cx = (_f(m, "x0") + _f(m, "x1")) / 2

                def dist(r):
                    a, b = spans[r]
                    return 0.0 if a <= cx <= b else min(abs(cx - a), abs(cx - b))
                ds = sorted((dist(r), r) for r in spans)
                # Run N, N4 (review A1): an X no nearer one option than
                # another (within TIE_PT) has no owner the page can name. It
                # is never handed to the first option: every tied option gets
                # None — "the page does not say" — and the caller flags it.
                #
                # Run Q (review N4 gap): CONTAINMENT IS DECISIVE. An X whose
                # centre is inside exactly one option's span belongs to it,
                # however close the next option starts - the tie tolerance
                # is for an X sitting between options, not inside one.
                inside = [r for d, r in ds if d == 0.0]
                if len(inside) == 1:
                    out[inside[0]] = True
                    continue
                tied = [r for d, r in ds if d - ds[0][0] <= TIE_PT]
                if len(tied) > 1:
                    for r in tied:
                        if out.get(r) is not True:
                            out[r] = None
                    continue
                out[ds[0][1]] = True
            return out
    return {}


# ── unwitnessed duplicates ──────────────────────────────────────────────────

def _letters(s) -> str:
    return re.sub(r"[^a-z]", "", str(s or "").casefold())


def _label_words(label):
    rest = _SLOT_BOX.sub("", str(label or ""))
    return [w for w in re.sub(r"[^a-z]+", " ", rest.casefold()).split()
            if len(w) >= 4 and w not in _GENERIC]


def _line_index(source, lines):
    s = re.sub(r"\s+", " ", str(source or "")).strip().casefold()
    if not s:
        return None
    for i, ln in enumerate(lines):
        t = " ".join(str(w.get("text", "")) for w in ln).casefold()
        if s and (s == t or s in t):
            return i
    return None


def witnessed(label, value, source, lines) -> bool:
    if re.sub(r"\s+", " ", str(source or "")).strip().casefold() == \
            re.sub(r"\s+", " ", str(value or "")).strip().casefold():
        return True
    words = _label_words(label)
    i = _line_index(source, lines)
    if not words or i is None:
        return False
    near = _letters(" ".join(str(w.get("text", "")) for k in (i - 1, i)
                             if 0 <= k < len(lines) for w in lines[k]))
    return any(w in near for w in words)


def _in_quote(value, source) -> bool:
    k = _key(value)
    if k.startswith("#"):
        return any(_key(t) == k for t in str(source or "").split())
    return k in re.sub(r"\s+", " ", str(source or "")).casefold()


def are_aliases(a, b) -> bool:
    wa, wb = set(_label_words(a)), set(_label_words(b))
    if wa and wa == wb:
        return True
    try:
        import aliases as AL
        for fn in ("same_meaning", "are_aliases"):
            f = getattr(AL, fn, None)
            if f:
                return bool(f(a, b))
    except Exception:
        pass
    return False


def unwitnessed_duplicates(fields, values, provenance, lines):
    """[(loser ref, keeper label)] — the copy of a value two non-alias slots
    share that only one of them is witnessed for."""
    by_val = {}
    for f in fields:
        v = values.get(f["ref"])
        if not str(v or "").strip() or _is_mark(v)                 or (provenance.get(f["ref"]) or {}).get("machine_read"):
            continue
        by_val.setdefault(_key(v), []).append(f)
    out = []
    for group in by_val.values():
        if len(group) < 2:
            continue
        wit = {f["ref"]: witnessed(f["row_label"], values[f["ref"]],
                                   (provenance.get(f["ref"]) or {}).get("source"), lines)
               for f in group}
        keepers = [f for f in group if wit[f["ref"]]]
        if not keepers:
            continue
        for f in group:
            if wit[f["ref"]]:
                continue
            # Only a copy that GROUNDS in its own quote is silent; one whose
            # quote does not hold it is already low and flagged by grounding,
            # and a visible wrong value is left visible.
            src = str((provenance.get(f["ref"]) or {}).get("source") or "")
            if not _in_quote(values[f["ref"]], src):
                continue
            if any(are_aliases(f["row_label"], k["row_label"]) for k in keepers):
                continue
            out.append((f["ref"], keepers[0]["row_label"]))
    return out


# ── the pass over field slots ───────────────────────────────────────────────

_IDENT = re.compile(r"\b(number|no|id|code|ref|control|account|serial)\b", re.I)
#: a slot naming a bank (not a bank ACCOUNT number or sort code)
_BANK_SLOT = re.compile(r"\bbank\b(?!\s*(?:account|acct|no|number|code|sort|routing|#))", re.I)
_BANK_WORDS = re.compile(
    r"\b(?:bank|banque|banco|bancorp|credit\s+union|building\s+society|savings|trust"
    r"|financial|treasury|plc\s+bank|n\.?a\.?)\b", re.I)


def _run_on_line(value, lines):
    """(line, [words]) where the words of `value` are printed consecutively."""
    toks = str(value or "").split()
    if not toks:
        return None, []
    for ln in lines:
        ws = [w for w in ln if str(w.get("text", "")).strip()]
        for i in range(len(ws) - len(toks) + 1):
            if all(str(ws[i + k].get("text")) == toks[k] for k in range(len(toks))):
                return ln, ws[i:i + len(toks)]
    return None, []


def own_box_part(value, label, lines):
    """A3: the words of a box value printed inside its OWN box. Job 48 read
    `0000005712UUQ CKR5 16260` for Box d, the line under `d Control number |
    Dept. | Corp. | Employer use only`. The box ends where its caption line
    prints a heading that is not a word of the slot's own label."""
    own = slot_box(label)
    if not own or len(str(value or "").split()) < 2:
        return value
    _ln, run = _run_on_line(value, lines)
    if not run:
        return value
    first = run[0]
    if box_owner(first, lines) is None or not same_box(own, box_owner(first, lines)):
        return value
    lab = _letters(_SLOT_BOX.sub("", str(label or "")))
    for cap in lines:
        for code, w in _codes_on(cap):
            if not same_box(own, code) or w.get("page") != first.get("page"):
                continue
            dy = _f(first, "top") - _f(w, "top")
            if not (0 < dy <= 40) or _f(w, "x0") > _f(first, "x0") + 2:
                continue
            after = [x for x in cap if _f(x, "x0") > _f(w, "x1")]
            edge = next((_f(x, "x0") for x in after
                         if len(_letters(x.get("text"))) >= 2
                         and _letters(x.get("text")) not in lab), None)
            if edge is None:
                return value
            kept = [x for x in run if _f(x, "x0") < edge - 1]
            if kept and len(kept) < len(run):
                return " ".join(str(x.get("text")) for x in kept)
            return value
    return value


def printed_spacing(value, label, lines):
    """A3: an identifier keeps the space the page prints inside it."""
    if not (slot_box(label) or _IDENT.search(str(label or ""))):
        return value
    v = str(value or "").strip()
    if not v or " " in v:
        return value
    for ln in lines:
        for w in ln:
            if str(w.get("text", "")) == v and w.get("spaced"):
                return w["spaced"]
    return value


def settle_fields(fields, values, conf, provenance, lines, notes, rewritten=None,
                  ambiguous=None):
    """Apply rules 0-3 to the field answers in place. Returns the refs cleared;
    refs whose value was rewritten (trimmed to their box, spacing restored) are
    appended to `rewritten` for the caller to re-grade; (ref, reason) for a
    checkbox the page leaves undecided is appended to `ambiguous` (Run N, N4)
    for the caller to flag."""
    if rewritten is None:
        rewritten = []
    if ambiguous is None:
        ambiguous = []
    if not lines:
        return []
    cleared = []

    def clear(f, why):
        v = values.pop(f["ref"], None)
        conf.pop(f["ref"], None)
        provenance.pop(f["ref"], None)
        cleared.append(f["ref"])
        notes.append(f'{f["row_label"]}: answer {str(v or "")[:40]!r} cleared — {why}')

    def machine_read(f):
        # a widget value (Run B form lane) is one value in one box: better
        # evidence than any reading of the flattened text layer
        return bool((provenance.get(f["ref"]) or {}).get("machine_read"))

    # 0. a box value that runs into the neighbouring boxes, and an identifier
    #    the reader glued across a printed space (A3)
    for f in fields:
        v = values.get(f["ref"])
        if not str(v or "").strip() or _is_mark(v) or machine_read(f):
            continue
        fixed = own_box_part(v, f["row_label"], lines)
        if fixed != v:
            notes.append(f'{f["row_label"]}: kept only the part printed in its own '
                         f'box ({str(v)[:40]!r} -> {fixed!r})')
        spaced = printed_spacing(fixed, f["row_label"], lines)
        if spaced != fixed:
            notes.append(f'{f["row_label"]}: printed spacing kept ({spaced!r})')
        if spaced != v:
            values[f["ref"]] = spaced
            rewritten.append(f["ref"])

    # 1. a box value printed in another box
    for f in fields:
        v = values.get(f["ref"])
        if not str(v or "").strip() or _is_mark(v) or machine_read(f):
            continue
        other = foreign_value(v, f["row_label"], lines,
                              (provenance.get(f["ref"]) or {}).get("source", ""))
        if other:
            clear(f, f"{str(v)[:40]!r} is printed in box {other}, not box "
                     f"{slot_box(f['row_label'])}")

    # 2. checkbox groups
    groups = {}
    for f in fields:
        b = slot_box(f["row_label"])
        if b:
            groups.setdefault(b, []).append(f)
    for b, fs in groups.items():
        if len(fs) < 2:
            continue
        vals = [(f, values.get(f["ref"])) for f in fs]
        if not any(_is_mark(v) for _f2, v in vals) or any(machine_read(x) for x in fs):
            continue
        if any(str(v or "").strip() and not _is_mark(v) for _f2, v in vals):
            continue
        verdict = checkbox_marks(vals, lines)
        if not verdict:
            continue
        tied = [f for f, _v in vals if f["ref"] in verdict and verdict[f["ref"]] is None]
        if tied:
            names = " and ".join(repr(f["row_label"]) for f in tied)
            why = (f"ambiguous: the X on the page sits exactly between {names}, "
                   f"so the page does not say which box {b} option is checked")
            for f, v in vals:
                if f in tied and _is_mark(v):
                    ambiguous.append((f["ref"], why))
            if not any(f in tied and _is_mark(v) for f, v in vals):
                # the answer chose no tied option: still say the page is unclear
                ambiguous.append((tied[0]["ref"], why))
        for f, v in vals:
            want = verdict.get(f["ref"])
            if want is False and _is_mark(v):
                clear(f, f"the X on the page sits under another box {b} option")
            elif want is True and not _is_mark(v):
                values[f["ref"]] = "X"
                provenance[f["ref"]] = {"source": "X", "page": None,
                                        "grounded": True, "machine_read": "checkbox"}
                notes.append(f'{f["row_label"]}: X read from its own column')

    # 4. Run G review (batch 1, item 1): a BANK slot answered with another
    #    party's name. Job 42 put the vendor's own name into Remit To Bank
    #    from "Payment within 30 days to Harwood Design Studio Ltd · Sort code
    #    ..."; no bank is printed. Cleared when the value names no bank, its
    #    quote prints no word of the label, and the page prints the value
    #    again on another line that says nothing of a bank (a party block or
    #    the letterhead). A bank named once in a payment line is kept.
    for f in fields:
        v = values.get(f["ref"])
        lab = str(f.get("row_label") or "")
        if not str(v or "").strip() or machine_read(f) or not _BANK_SLOT.search(lab):
            continue
        if _BANK_WORDS.search(str(v)):
            continue
        src = str((provenance.get(f["ref"]) or {}).get("source") or "")
        if _BANK_WORDS.search(src) or witnessed(lab, v, src, lines):
            continue
        qi = _line_index(src, lines)
        want = re.sub(r"\s+", " ", str(v)).strip().casefold()
        elsewhere = [i for i, ln in enumerate(lines) if i != qi and want in
                     " ".join(str(w.get("text", "")) for w in ln).casefold()]
        if elsewhere and not any(_BANK_WORDS.search(
                " ".join(str(w.get("text", "")) for w in lines[i])) for i in elsewhere):
            clear(f, f"{str(v)[:40]!r} is a party named elsewhere on the page; "
                     f"no bank is printed for {lab!r}")

    # 3. unwitnessed duplicates
    for ref, keeper in unwitnessed_duplicates(fields, values, provenance, lines):
        f = next(x for x in fields if x["ref"] == ref)
        clear(f, f"the same value belongs to {keeper!r}; nothing printed beside "
                 f"it names {f['row_label']!r}")
    return cleared


def foreign_box_rows(table_name, raw_rows, headers, lines):
    """(kept rows, [(row, owner box)]) — rows of a box-coded table whose every
    amount is printed in a different box."""
    own = slot_box(table_name) or next((slot_box(h) for h in headers if slot_box(h)), "")
    if not own or not lines:
        return raw_rows, []
    kept, out = [], []
    for r in raw_rows:
        cells = r.get("cells") if isinstance(r, dict) and isinstance(r.get("cells"), dict) else r
        if not isinstance(cells, dict):
            kept.append(r)
            continue
        owners = []
        for k, v in cells.items():
            if str(k).startswith("_") or not str(v or "").strip():
                continue
            if not re.fullmatch(r"[$£€]?\(?-?[\d,]+\.\d{2}\)?-?", str(v).strip()):
                continue
            occ = occurrences(v, lines)
            os_ = [box_owner(w, lines) for w in occ]
            if not occ or any(o is None or same_box(own, o) for o in os_):
                owners = None
                break
            owners.append(os_[0])
        if owners:
            out.append((r, owners[0]))
        else:
            kept.append(r)
    return kept, out


# ── fragment rows (A6) ──────────────────────────────────────────────────────

def merge_fragment_rows(rows, headers, quotes=None):
    """(rows, n merged). A band holding ONE entity — its key column (the
    first heading) filled on exactly one row, the first — whose other rows
    have no key and fill only columns no earlier row filled, is one row
    answered in pieces: the pieces merge into it. Anything else (a second
    key, an overlapping column) is left exactly as it is."""
    if len(rows) < 2 or not headers:
        return rows, 0
    key = headers[0]

    def filled(r):
        return {h for h in headers if str(r.get(h, "") or "").strip()}

    if not str(rows[0].get(key, "") or "").strip():
        return rows, 0
    if any(str(r.get(key, "") or "").strip() for r in rows[1:]):
        return rows, 0
    # Run N, N5 (review A6): disjoint columns are not proof of one entity —
    # two real rows (Checking-A's debit, Savings-B's credit with its key
    # missed) are disjoint too. A piece belongs to the keyed row only when it
    # was read from the SAME record: the same quoted line, or a quote that
    # prints the keyed row's own key as a whole word. No quote, no merge.
    # `quotes(row)` is the model's own quote for the row (before re-anchoring
    # moved it to a line); without one, the row's `_source`.
    def quote(r):
        q = quotes(r) if quotes else None
        q = q if q else r.get("_source", "")
        return re.sub(r"\s+", " ", str(q or "")).strip().casefold()

    k0 = str(rows[0].get(key, "") or "").strip()
    src0 = quote(rows[0])
    kpat = re.compile(r"(?<![0-9a-z])" + re.escape(k0.casefold()) + r"(?![0-9a-z])")

    def same_record(r):
        s = quote(r)
        return bool(s) and (s == src0 or bool(kpat.search(s)))

    seen = filled(rows[0])
    for r in rows[1:]:
        f = filled(r)
        if not f or f & seen or not same_record(r):
            return rows, 0
        seen |= f
    merged = dict(rows[0])
    for r in rows[1:]:
        for h in filled(r):
            merged[h] = r[h]
        bad = list(merged.get("_ungrounded") or []) + list(r.get("_ungrounded") or [])
        if bad:
            merged["_ungrounded"] = list(dict.fromkeys(bad))
        order = ("low", "unverified", "grounded", "high")
        a, b = str(merged.get("_confidence", "")), str(r.get("_confidence", ""))
        if a in order and b in order and order.index(b) < order.index(a):
            merged["_confidence"] = b
    return [merged], len(rows) - 1
