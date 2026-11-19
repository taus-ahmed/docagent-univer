"""Template labels matched by MEANING, not wording (Run B, B2).

A user's template says what THEY call a thing; the document says what ITS
author called it. "Delivered To" and "Ship To" are one slot. The engine used
to treat a heading the document does not print word for word as a template
describing something the document lacks (`unprinted_headers`), and the
prompt never told the model that wording may differ.

Three sources, in order:
1. the template's own `aliases` for a cell (optional; a grid cell may carry
   ``"aliases": ["Sent To", ...]`` - backward compatible, never required);
2. one small, generic table of equivalent phrases for invoice / PO / receipt
   / bank / card / W-2 / 1099 vocabulary (`GROUPS`) - data, not rules;
3. the label with its QUALIFIER words removed ("Running Balance" -> "Balance",
   "Item Description" -> "Description"), when something is left.

Nothing here decides a value. Aliases feed the prompt, the printed-heading
diagnostic and the template-columns check; they never flag by themselves.
"""
from __future__ import annotations

import re

#: Equivalent phrasings. Each inner list is one meaning. Keep it SMALL: a
#: phrase belongs here only if it is the ordinary way documents of these
#: families print the same field.
GROUPS = [
    ["ship to", "delivered to", "deliver to", "sent to", "shipping address", "ship-to"],
    ["bill to", "sold to", "invoice to", "billing address", "customer"],
    ["total due", "amount due", "amount payable", "balance due", "total amount due",
     "please pay", "pay this amount"],
    ["invoice number", "invoice no", "invoice #", "inv no"],
    ["po number", "purchase order number", "po #", "po no", "order number"],
    ["receipt number", "transaction number", "ticket number", "check number"],
    ["running balance", "balance", "ledger balance", "daily balance"],
    ["withdrawal", "withdrawals", "debit", "debits", "payments", "money out"],
    ["deposit", "deposits", "credit", "credits", "money in"],
    ["posting date", "post date", "posted"],
    ["transaction date", "trans date", "date"],
    ["description", "details", "particulars", "item", "item description", "memo"],
    ["quantity", "qty", "units"],
    ["unit price", "rate", "price", "unit cost"],
    ["line total", "extended", "ext price"],
    ["payment due date", "payment due", "due date", "pay by"],
    ["account number last 4", "last 4", "card ending", "account ending", "ending in"],
    ["opening balance", "beginning balance", "previous balance", "balance forward"],
    ["closing balance", "ending balance", "new balance"],
    ["box 1 wages tips other compensation", "wages, tips, other compensation", "wages"],
    ["box 2 federal income tax withheld", "federal income tax withheld"],
    ["employee ssn", "employee's social security number", "social security number", "ssn"],
    ["employer ein", "employer identification number", "ein"],
    ["payer tin", "payer's tin", "payer's federal identification number"],
    ["recipient tin", "recipient's tin", "recipient's identification number"],
    ["nonemployee compensation", "box 1 nonemployee compensation"],
]

#: Words that QUALIFY a heading rather than name it.
_QUALIFIERS = {"item", "line", "running", "posting", "transaction", "listed",
               "statement", "txn"}     # never "total": a total is not its column


def _norm(s) -> str:
    s = str(s or "").casefold().replace("’", "'")
    return re.sub(r"\s+", " ", re.sub(r"[^0-9a-z'#&]+", " ", s)).strip()


def _strip_box(s: str) -> str:
    return re.sub(r"^(?:box\s+)?(?:\d{1,2}[a-z]?|[a-f])\s+(?=\w)", "", s).strip()


def aliases_for(label, declared=()) -> list[str]:
    """Other wordings of `label`, most specific first, without `label`."""
    n = _norm(label)
    out = [str(a) for a in (declared or ()) if str(a).strip()]
    for group in GROUPS:
        ng = [_norm(g) for g in group]
        if n in ng or _strip_box(n) in ng:
            out += [g for g, x in zip(group, ng) if x != n]
    words = n.split()
    core = [w for w in words if w not in _QUALIFIERS]
    if core and len(core) < len(words):
        out.append(" ".join(core))
    seen, uniq = {n}, []
    for a in out:
        if _norm(a) not in seen:
            seen.add(_norm(a))
            uniq.append(a)
    return uniq


def cell_aliases(grid, row, col) -> list[str]:
    """The template's own optional `aliases` on a grid cell."""
    cell = ((grid or {}).get("cells") or {}).get(f"{row},{col}") or {}
    a = cell.get("aliases") if isinstance(cell, dict) else None
    if isinstance(a, str):
        a = [x.strip() for x in a.split(",")]
    return [x for x in (a or []) if isinstance(x, str) and x.strip()]


def phrase_printed(lines, phrase) -> bool:
    """The whole phrase, as consecutive words, on one printed line."""
    p = _norm(phrase)
    if not p:
        return False
    pat = re.compile(r"(?<![0-9a-z])" + re.escape(p) + r"(?![0-9a-z])")
    for ln in lines or []:
        if pat.search(_norm(" ".join(str(w.get("text", "")) for w in ln))):
            return True
    return False


def printed_by_meaning(lines, label, declared=()) -> bool:
    """True when the label (by the loose every-word rule of
    `unprinted_headers`) or any alias (as a whole phrase) is printed."""
    from text_layer import unprinted_headers
    if not unprinted_headers(lines, [label]):
        return True
    return any(phrase_printed(lines, a) for a in aliases_for(label, declared))


def unprinted_labels(lines, labels) -> list[str]:
    """Labels with no LITERAL match in the page words (B2.2 diagnostic)."""
    from text_layer import unprinted_headers
    return unprinted_headers(lines, labels)


def _declared_for_field(grid, f) -> list[str]:
    """Aliases the template declares on a field's value cell or on any label
    cell to its left on the same row."""
    out = cell_aliases(grid, f.get("row"), f.get("col"))
    for c in range(int(f.get("col") or 0) - 1, -1, -1):
        out += cell_aliases(grid, f.get("row"), c)
    return out


def hints(slots, grid, lines) -> list[dict]:
    """[{slot, label, aliases}] - what the prompt says about wording.

    A slot gets a hint when the template DECLARES aliases for it (always
    given), or when its label is not printed literally and one of the generic
    aliases is - the model is then told the word the document actually uses.
    A slot printed as written gets nothing: there is nothing to say."""
    from text_layer import unprinted_headers
    out = []
    for f in slots.get("fields") or []:
        declared = _declared_for_field(grid, f)
        label = f["row_label"]
        found = []
        if lines and unprinted_headers(lines, [label]):
            found = [a for a in aliases_for(label) if a not in declared
                     and phrase_printed(lines, a)]
        if declared or found:
            out.append({"slot": f["slot_id"], "label": label,
                        "aliases": declared + found[:3]})
    for t in slots.get("tables") or []:
        for c in t.get("columns") or []:
            h = c.get("header") or ""
            declared = cell_aliases(grid, t.get("header_row"), c.get("col"))
            found = []
            if lines and h and unprinted_headers(lines, [h]):
                found = [a for a in aliases_for(h) if a not in declared
                         and phrase_printed(lines, a)]
            if declared or found:
                out.append({"slot": f'table "{t["name"]}" column', "label": h,
                            "aliases": declared + found[:3]})
    return out


def prompt_block(hint_list) -> str:
    if not hint_list:
        return ""
    rows = [f'  {h["slot"]} "{h["label"]}": the document may say '
            + ", ".join(f'"{a}"' for a in h["aliases"]) for h in hint_list]
    return ("WORDING: the template's labels and the document's wording can "
            "differ. Match every slot by MEANING, not by exact words - a value "
            "printed under a different label is still that slot's value. "
            "Known other wordings:\n" + "\n".join(rows) + "\n")


def diagnostics(slots, lines) -> dict:
    """B2.2, informational only: template labels with no LITERAL match in the
    page words, and which of those are printed under another wording."""
    from text_layer import unprinted_headers
    labels = [f["row_label"] for f in slots.get("fields") or []] + \
        [c.get("header") or "" for t in slots.get("tables") or []
         for c in t.get("columns") or []]
    literal = unprinted_headers(lines or [], [x for x in labels if x])
    by_meaning = [x for x in literal if printed_by_meaning(lines or [], x)]
    return {"labels": len(labels), "no_literal_match": literal,
            "printed_by_alias": by_meaning,
            "not_printed": [x for x in literal if x not in by_meaning]}
