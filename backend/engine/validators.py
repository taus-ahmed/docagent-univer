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
    fam = family_of(doc_type)
    out = []
    for v in REGISTRY.get(ANY, []) + (REGISTRY.get(fam, []) if fam != ANY else []):
        out.extend(v(ctx) or [])
    return out


_loaded = False


def _load():
    """Import the family modules once; each registers itself."""
    global _loaded
    if not _loaded:
        _loaded = True
        import cheque_validators  # noqa: F401
        import invoice_validators  # noqa: F401
        import bank_validators  # noqa: F401
        import payslip_validators  # noqa: F401
