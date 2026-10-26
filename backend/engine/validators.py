"""Per-family cross-field checks — one interface, one registry.

Grounding asks whether each value is on the page. A cross-field check asks
whether values AGREE with each other or with a rule of their kind: a cheque's
amount in figures against its amount in words, a routing number against the
ABA check digit, an invoice's lines against its total. Those rules belong to a
document FAMILY, and the generic engine must not know them — so each family
registers its validators here and slot extraction runs whatever is registered
for the family it was given, applying every result by the same three rules:

  fail        every affected value becomes exactly `low`, review_required,
              with the check's reason code
  unreadable  the reason code is added to every affected value; no level moves
  pass        recorded only (`evidence`); never raises a level — values that
              agree are not thereby measured

A family with nothing registered runs nothing. `ANY` holds checks that are a
property of a FIELD rather than of a family (a routing number is checkable on
a cheque, a statement or a pay stub alike) and runs for every family.

Reason codes: docs/OCR-READER-SEAM-DESIGN.md §12.
"""
from __future__ import annotations

from dataclasses import dataclass, field

PASS, FAIL, UNREADABLE = "pass", "fail", "unreadable"
ANY = "*"


@dataclass
class CheckContext:
    """What a validator may look at: the template's field slots
    (`{ref, row_label, ...}`), the extracted values by cell ref, and the
    record's own page texts (file order)."""
    fields: list
    values: dict
    pages: list
    #: the template's tables ({name, columns: [{key, header}]}) and the rows
    #: extracted for each ({name: [row]}); a row is addressed `<name>_rows[i]`.
    tables: list = field(default_factory=list)
    rows: dict = field(default_factory=dict)
    #: names of tables some gate dropped rows from (another region, a
    #: duplicate, an empty or malformed row): what is left is not the whole
    #: table, so a check summing or chaining its rows must not run.
    incomplete: set = field(default_factory=set)
    #: the template's locale, else the firm's (`locale:` in its YAML); None =
    #: let the document's own numbers decide (engine/amounts.py)
    locale: object = None
    #: {field ref: file page} where known; a row carries its own `_page`
    value_pages: dict = field(default_factory=dict)
    #: the FILE page number of each entry of `pages`, when the record is a
    #: slice of a file; None = pages are 1, 2, 3, …
    page_numbers: object = None
    #: the template's declared rules (engine/rules.py), run as one more check
    rules: list = field(default_factory=list)

    def texts(self):
        """Every extracted value of the record, fields and table cells."""
        out = [v for v in (self.values or {}).values()]
        for rows in (self.rows or {}).values():
            for r in rows or []:
                if isinstance(r, dict):
                    out += [v for k, v in r.items() if not str(k).startswith("_")]
        return out


@dataclass
class CheckResult:
    check: str                      # the validator's name
    status: str                     # PASS | FAIL | UNREADABLE
    slots: list = field(default_factory=list)       # affected cell refs
    reason: str = ""                # reason code, applied on FAIL / UNREADABLE
    #: {ref: {key: value}} merged into that value's provenance, any status.
    evidence: dict = field(default_factory=dict)
    #: [(label, value, sentence)] for `validation.flagged_fields`.
    flags: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    #: merged into the record's `validation`.
    validation: dict = field(default_factory=dict)
    #: a finding with no value to sit on (an empty slot) still needs review.
    needs_review: bool = False


#: family -> [validator(ctx) -> list[CheckResult]], run in registration order.
REGISTRY: dict = {}

#: Document-type names a template or inference may use, by family.
FAMILY_ALIASES = {
    "cheque": {"cheque", "check", "cheques", "checks", "bank_cheque"},
    "invoice": {"invoice", "sales_invoice", "purchase_invoice", "tax_invoice",
                "commercial_invoice"},
    "bank_statement": {"bank_statement", "bank_statements", "account_statement"},
    "payslip": {"payslip", "pay_slip", "payslips", "pay_stub", "paystub",
                "pay_stubs", "salary_slip"},
    "receipt": {"receipt", "receipts", "till_receipt", "expense_receipt",
                "sales_receipt", "cash_receipt"},
}


def register(family, validator):
    REGISTRY.setdefault(family, []).append(validator)
    return validator


def family_of(doc_type):
    t = str(doc_type or "").strip().lower()
    return next((fam for fam, names in FAMILY_ALIASES.items() if t in names), t)


def run_checks(doc_type, ctx):
    """Every result of every validator for this document type's family:
    the `ANY` checks first, then the family's own."""
    _load()
    from amounts import DOCUMENT_HINT, FIRM_LOCALE, document_hint
    # Locale hint, in order: the template's, the firm's, then the document's
    # own unambiguous numbers (engine/amounts.py).
    token = DOCUMENT_HINT.set(document_hint(ctx.texts(),
                                            ctx.locale or FIRM_LOCALE.get()))
    try:
        return _run(fam=family_of(doc_type), ctx=ctx)
    finally:
        DOCUMENT_HINT.reset(token)


def _slot_texts(ctx, ref):
    """The text(s) a result's slot holds: a field's value, or a row's cells."""
    if ref in (ctx.values or {}):
        return [ctx.values[ref]]
    import re as _re
    m = _re.fullmatch(r"(.+)_rows\[(\d+)\]", str(ref))
    if m:
        rows = (ctx.rows or {}).get(m.group(1)) or []
        i = int(m.group(2))
        if i < len(rows) and isinstance(rows[i], dict):
            return [v for k, v in rows[i].items() if not str(k).startswith("_")]
    return []


#: checks about one value's own notation: no currency comparison applies
_PER_VALUE = {"number_notation", "date_notation", "language_check"}


def _currency_gate(res, ctx):
    """CURRENCY CONSISTENCY (Part 1.5), for every check that compares or sums
    amounts: a result over values in two currencies is not a result. Mixed
    currencies make it a FAIL `currency_mismatch` (values exactly low);
    markers that may name different currencies make it UNREADABLE
    `currency_ambiguous` (review, no level moves)."""
    from amounts import CURRENCY_AMBIGUOUS, CURRENCY_MISMATCH, currency_agreement
    if res.check in _PER_VALUE or res.status not in (PASS, FAIL) or len(res.slots) < 2:
        return res
    texts = [t for ref in res.slots for t in _slot_texts(ctx, ref)]
    verdict, named = currency_agreement(texts)
    if verdict == "ok":
        return res
    said = (f"the {res.check} check compares amounts in "
            f"{'different currencies' if verdict == CURRENCY_MISMATCH else 'currencies that may differ'}"
            f" ({', '.join(named)}); it was not decided on them")
    return CheckResult(res.check, FAIL if verdict == CURRENCY_MISMATCH else UNREADABLE,
                       list(res.slots), verdict, evidence=res.evidence,
                       flags=[(res.check, "", said)], notes=[said],
                       validation={**res.validation, "currency_check": verdict},
                       needs_review=True)


def _run(fam, ctx):
    out = []
    for v in REGISTRY.get(ANY, []) + (REGISTRY.get(fam, []) if fam != ANY else []):
        try:
            out.extend(_currency_gate(r, ctx) for r in (v(ctx) or []))
        except Exception as exc:
            # A check that cannot run is not a check that passed: say so on
            # the record and send it for review, never take the record down.
            name = getattr(v, "__name__", "check")
            said = (f"the {name} check could not run ({type(exc).__name__}: "
                    f"{exc}); this record was not checked by it")
            out.append(CheckResult(name, UNREADABLE, [], "", needs_review=True,
                                   flags=[(name, "", said)], notes=[said]))
    return out


_loaded = False


def _load():
    """Import the family modules once; each registers itself."""
    global _loaded
    if not _loaded:
        _loaded = True
        import notation_validators  # noqa: F401
        import date_validators  # noqa: F401
        import language_validators  # noqa: F401
        import identifier_validators  # noqa: F401
        import cheque_validators  # noqa: F401
        import invoice_validators  # noqa: F401
        import bank_validators  # noqa: F401
        import payslip_validators  # noqa: F401
        import receipt_validators  # noqa: F401
        import rules  # noqa: F401  (a template's declared rules, Part 3.1)
