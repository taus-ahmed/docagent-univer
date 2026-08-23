"""
DocAgent — Canonical field vocabulary (Phase 9)

Inference names the columns, and naming is the one thing it does not do the
same way twice: "Doc No" or "Document Number", "Company EIN" or "Company Tax
ID", "Payee Name" or "Drawer Company Name" for the party who signed a cheque.
Temperature 0 removed the sampling half of that. The rest is structural — "what
should this column be called" has several correct answers, and no decoding
setting can pick one.

So inference stops being asked to INVENT names and is asked to CLASSIFY into a
closed set instead, per document type, with an escape hatch for values the set
does not cover. A closed-set classification is reproducible in a way a naming
task is not, and it is also the thing a customer can be shown in advance.

WHERE THE NAMES COME FROM
-------------------------
`prompt_registry.PROMPT_REGISTRY[type]` already carries `required_fields`,
`numeric_fields` and `date_fields` for 12 document types. Those keys are the
vocabulary; this module renders them as the labels a person reads in a
spreadsheet, and says which are money and which are dates.

The rendering is STANDARD ACCOUNTING AND BANKING TERMINOLOGY, deliberately not
whatever the test fixtures' gold labels happen to say. Where the two disagree,
the standard term wins and the disagreement is recorded in `GOLD_DIVERGENCE`
below rather than being papered over — a regression suite is not the product's
customers, and tuning the vocabulary to 63 PDFs would produce a vocabulary that
fits only those 63 PDFs.
"""

import re

#: Where plain title-casing of the registry key is wrong, ambiguous, or not the
#: term the trade actually uses. Everything not listed here is title-cased.
_DISPLAY = {
    # Cheques. The party who draws and signs a cheque is the DRAWER; the party
    # it is payable to is the PAYEE. A cheque carries two amounts — the figures
    # ("courtesy amount") and the words ("legal amount") — and naming either of
    # them just "Amount" loses which one it is.
    "drawer_name": "Drawer Name",
    "amount_figures": "Amount in Figures",
    "amount_words": "Amount in Words",
    "micr_line": "MICR Line",
    "routing_number": "Routing Number",
    "account_number": "Account Number",
    "authorized_by": "Authorized By",
    # Payroll. A payslip prints "Pay Date" and "Pay Period", not "Payment
    # Date" — the registry key is payment_date, the printed term is Pay Date.
    "payment_date": "Pay Date",
    "pay_period_from": "Pay Period From",
    "pay_period_to": "Pay Period To",
    # Identifiers and dates.
    "po_number": "PO Number",
    "po_date": "PO Date",
    "as_at_date": "As At Date",
    "taxpayer_id": "Taxpayer ID",
    # Statements.
    "statement_period_from": "Statement Period From",
    "statement_period_to": "Statement Period To",
    # Income statement.
    "income_tax_expense": "Income Tax Expense",
    "operating_income": "Operating Income",
    "gross_profit": "Gross Profit",
    "total_revenue": "Total Revenue",
    "net_income": "Net Income",
}

#: Standard terms for a document type that `prompt_registry` does not carry.
#: A CLOSED vocabulary with a hole in it does not merely mislabel the missing
#: value — it LOSES it: told to prefer the listed names, the model dropped the
#: employer from a payslip and the approval status from an expense report
#: rather than reaching for the "other:" escape. These are values the document
#: type states as a matter of course, so they belong in the list.
_EXTRA = {
    "payslip": [
        ("employer_name", "text"),   # a payslip names both parties, not one
        ("employee_id", "text"),
        ("pay_period", "date"),      # commonly printed as ONE span, not from/to
        ("total_earnings", "money"),
    ],
    "expense_report": [
        ("status", "text"),          # Approved / Pending / Rejected
        ("report_number", "text"),
        ("purpose", "text"),
    ],
    "sales_invoice": [
        ("payment_terms", "text"),
        ("status", "text"),          # PAID / OUTSTANDING / OVERDUE
    ],
    "purchase_order": [
        ("payment_terms", "text"),
        ("ship_to", "text"),
    ],
    "bank_statement": [
        ("bank_name", "text"),
        ("statement_number", "text"),
    ],
    "balance_sheet": [
        ("company_identifier", "text"),
    ],
    "income_statement": [
        ("company_identifier", "text"),
    ],
}

#: Recorded, not resolved. These are places where this repository's gold labels
#: use a term that is NOT the standard one. The vocabulary uses the standard
#: term; the harness will show these as `renamed` against gold, which is the
#: correct reading — the engine is right and the label is not.
GOLD_DIVERGENCE = {
    "cheque": [
        ("Payer Name", "Drawer Name",
         "The party who writes and signs a cheque is the DRAWER (UCC Art. 3 "
         "and ordinary banking usage). 'Payer' is colloquial and is also "
         "confusable with the payee."),
        ("Amount", "Amount in Figures",
         "A cheque states its amount twice — in figures and in words — and "
         "they can disagree, which is the whole reason both are printed. "
         "'Amount' does not say which one was read."),
    ],
}


def _title(key: str) -> str:
    return " ".join(w.capitalize() for w in str(key).split("_"))


def _registry():
    try:
        from app.api.routes.prompt_registry import PROMPT_REGISTRY
        return PROMPT_REGISTRY
    except Exception:
        return {}


def canonical_fields(doc_type: str):
    """[{name, kind}] — the closed label set for one document type.

    `kind` is money | date | text, taken from the registry's own
    numeric_fields / date_fields. Returns [] for an unknown type, which means
    "name things freely", the behaviour before this module existed.
    """
    entry = (_registry() or {}).get(str(doc_type or "").strip())
    if not isinstance(entry, dict):
        return []
    money = set(entry.get("numeric_fields") or [])
    dates = set(entry.get("date_fields") or [])
    out, seen = [], set()
    for key in (list(entry.get("required_fields") or [])
                + sorted(money) + sorted(dates)):
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": _DISPLAY.get(key, _title(key)),
            "kind": "money" if key in money else ("date" if key in dates else "text"),
        })
    for key, kind in _EXTRA.get(str(doc_type or "").strip(), []):
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": _DISPLAY.get(key, _title(key)), "kind": kind})
    return out


def vocabulary_block(doc_type: str) -> str:
    """The closed-set instruction added to the inference prompt. '' when the
    type is unknown, so nothing changes for documents we have no vocabulary
    for."""
    fields = canonical_fields(doc_type)
    if not fields:
        return ""
    by_kind = {"money": [], "date": [], "text": []}
    for f in fields:
        by_kind[f["kind"]].append(f["name"])
    kind = str(doc_type).replace('_', ' ').upper()
    article = "AN" if kind[:1] in "AEIOU" else "A"
    p = ["",
         f"STANDARD NAMES FOR {article} {kind}:"]
    if by_kind["text"]:
        p.append("  " + " | ".join(by_kind["text"]))
    if by_kind["money"]:
        p.append("  amounts: " + " | ".join(by_kind["money"]))
    if by_kind["date"]:
        p.append("  dates:   " + " | ".join(by_kind["date"]))
    p.append("")
    p.append("HOW TO NAME A FIELD, in this order:")
    p.append("  1. If the document PRINTS a label for the value, use that "
             "label exactly as printed. An invoice headed \"Bill To:\" has a "
             "Bill To field, not a Customer Name field; a page printing "
             "\"Doc No:\" has a Doc No field, not a Document Number field. The "
             "page decides, so the name is the same on every run and it is "
             "the name your reader already sees.")
    p.append("  2. If the document prints NO label — a letterhead address, a "
             "signature, a stamp, the numbers inside a cheque's MICR line, an "
             "amount sitting in its own box — take the name from the list "
             "above. That is what these values are called in accounting "
             "practice, and it is why the list exists.")
    p.append("  3. If the printed label does not say WHICH value it is, "
             "prefer the list's more precise term. A cheque prints its amount "
             "twice, in figures and in words; \"Amount\" does not say which, "
             "so use Amount in Figures and Amount in Words.")
    p.append("  4. Otherwise write \"other: \" and your own short label, e.g. "
             "\"other: Bank Address\".")
    p.append("")
    p.append("THE LIST NEVER LIMITS WHAT YOU REPORT. It fixes what things are "
             "CALLED, not which values you return. Every value printed on the "
             "page still gets a field, exactly as item 3 says. Dropping a "
             "printed value because no listed name fits it is the worst thing "
             "you can do here — that is what rule 4 is for.")
    p.append("Do not force a listed name onto a value the document does not "
             "state, and never invent a value to fill a name.")
    p.append("")
    return "\n".join(p)


_OTHER = re.compile(r"^\s*other\s*:\s*", re.I)


def split_other(label: str):
    """('Bank Address', True) for 'other: Bank Address'; (label, False) else.

    The prefix is how the model tells us a value fell outside the vocabulary.
    It is stripped before the label reaches a spreadsheet — the user should see
    "Bank Address", not "other: Bank Address" — but the fact is kept, because
    the share of values needing it is how we know whether the vocabulary is
    wide enough.
    """
    s = str(label or "")
    if _OTHER.match(s):
        return _OTHER.sub("", s).strip(), True
    return s.strip(), False
