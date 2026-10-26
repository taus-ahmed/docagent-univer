# Adding a document family

A **family** is a kind of document whose values must agree with each other: an
invoice's lines with its subtotal, a statement's opening and closing balances,
a payslip's gross and net. Extraction is the same for every family (one slot
per template cell, grounded on the page). What differs is the **checks** that
run afterwards. There are two ways to add them.

| | Declared rules | Coded validators |
|---|---|---|
| Written as | JSON on the template | Python in `backend/engine/<family>_validators.py` |
| Needs a deploy | no | yes |
| Who | whoever owns the template | a developer |
| Can express | the ten rule types below | anything |
| Applies to | documents extracted with that template | every document of the family, any template |

Start with declared rules. Write code only for what they cannot say (see
"Limits").

Whichever way a check is written, the outcome rules are the same (`engine/validators.py`):

- **FAIL**: every value the check names becomes exactly `low` and is sent for review.
- **UNREADABLE**: a reason is added and review is required; no level moves.
- **PASS**: recorded as evidence only, and never raises a level.

A check therefore cannot make a value look better than grounding already did.

## 1. Declared rules (no code)

A template carries `rules`, a list, on its grid JSON (the template's
`description`). The editor keeps them on every save. A rule that names a label
that no longer exists **blocks the save** with the engine's own message.

```json
"rules": [
  {"name": "lines_sum",   "type": "sum_equals", "terms": ["items.Amount"], "total": "Subtotal"},
  {"name": "grand_total", "type": "sum_equals",
   "terms": ["Subtotal", "Shipping?", "Tax?", "-Discount?"], "total": "Total"},
  {"name": "line_amount", "type": "product", "factors": ["items.Qty", "items.Unit Price"],
   "result": "items.Amount"},
  {"name": "due_after_issue", "type": "date_order", "first": "Invoice Date", "then": "Due Date"},
  {"name": "po_format", "type": "regex", "value": "PO Number", "pattern": "PO-\\d{4}-\\d{4}"},
  {"name": "late_fee_needs_terms", "type": "required_if", "value": "Payment Terms", "if": "Late Fee"}
]
```

### Naming values

Use the template's own words:

| Write | Means |
|---|---|
| `Subtotal` | the field whose label is "Subtotal" (case and spacing ignored); a cell ref such as `B7` also works |
| `items.Amount` | the "Amount" column of the table named `items` (its rows) |
| `-Discount` | in `terms`: subtract the amount's magnitude, as printed discounts usually are |
| `Tax?` | optional: if empty, it counts as nothing |

If a required value is empty, the rule **does not run**: an absent subtotal is
not a wrong one. To demand that a value is present, use `required_if`.

### The ten types

| type | keys | checks | runs per row when given a column |
|---|---|---|---|
| `sum_equals` | `terms`, `total`, `tolerance`? | terms add up to total; tolerance is one cent per summed amount unless set | no (sums the column) |
| `equals` | `left`, `right` | equal as amounts when both are amounts, else as text | — |
| `product` | `factors`, `result` | factors multiply to result | yes |
| `range` | `value`, `min`?, `max`? | value lies within the bounds | yes |
| `regex` | `value`, `pattern` | the whole value matches | yes |
| `id_type` | `value`, `id_type` | passes the identifier plug-in (`aba`, `iban`, `gstin`, `pan`, `vat`, … — `engine/identifiers`) | yes |
| `date_order` | `first`, `then`, `strict`? | first is on/before then; an ambiguous date is UNREADABLE, never guessed | — |
| `count_matches` | `table`, `count` | the table has as many rows as the field says | — |
| `currency_same` | `values` | every amount is in one currency | — |
| `required_if` | `value`, `if`, `equals`? | value is present when `if` is filled (and equals the text) | — |

Amounts and dates are read by the shared parsers (`engine/amounts.py` and
`engine/dates.py`) using the template's locale, else the firm's, else the
document's own unambiguous numbers. An amount like `1,234` with nothing to
resolve it is **UNREADABLE**, not a guess.

### Reason codes

- `rule_failed:<name>`: the rule did not hold. The values are made `low`.
- `rule_unreadable:<name>`: the rule could not be decided, or is stated
  wrongly (unknown type, a reference to nothing, a bad pattern).

A wrongly stated rule is never skipped quietly. The review screen shows
"Template rule failed (lines_sum)". A rule's name is its reason code, so names
must be unique.

### Limits

These cannot be declared and stay in code:

- **A running balance**: each statement row's balance against the previous
  row's. Every rule reads one row, or a whole column, never the row before.
- **Finding values by meaning**: the coded invoice check finds the subtotal,
  tax and discount in *any* template by its labels (`invoice_validators.role`).
  A rule names the labels of *its own* template.
- **Guards**: the coded total check refuses to run when an unknown amount is
  printed between Subtotal and Total. A rule lists its terms explicitly, so the
  author decides.

### How well they agree with the coded checks

`tests/test_rules_equality.py` extracts every locale fixture twice: once with
the coded family checks, and once with only the equivalent declared rules
(`tests/rules_equivalents.py`).

- **14 of 16** fixtures mark exactly the same values `low`.
- The other two are statement corruptions (a dropped row, a swapped
  debit/credit). The coded check finds them through the running balance. The
  rules find them through the credit and debit column sums, which marks
  different values. Both send the document to review.

## 2. Coded validators

1. **Name the family.** Add its document-type names to `FAMILY_ALIASES` in
   `engine/validators.py`.
2. **Write the check.** Create `engine/<family>_validators.py` with functions
   `check(ctx) -> list[CheckResult]`, registered with `register("<family>", check)`.
   A check that applies to a *field* wherever it appears (a routing number)
   registers under `ANY`.
   - Read values from `ctx.values` and `ctx.rows`.
   - Parse with the shared parsers; never `float()`.
   - Return `UNREADABLE` when the values are present but cannot be read.
   - Skip a table named in `ctx.incomplete`: rows were dropped from it, and a
     sum over what is left would call correct values wrong.
3. **Load it.** Import the module in `validators._load()`.
4. **Register reason codes.** Use
   `python scripts/dev/add_reason.py codes.json`. It writes both
   `docs/OCR-READER-SEAM-DESIGN.md` §12 and `app/core/review.py`, and
   `tests/test_review_reasons.py` checks that they agree.
5. **Test.** Add a fixture to `tests/fixtures/make_locale_fixtures.py`
   (a clean document plus one corruption per defect) and check that each
   corruption raises its own flag, as `tests/test_locale_fixtures.py` does.
   Run both harness modes before merging: `97.2%` / `96.7%` must not move.

An identifier with a check digit is a **plug-in**, not a family:
`engine/identifiers/`, `register(name, check, reason_code)`. It is then usable
both from a cell's `id_type` and from an `id_type` rule.
