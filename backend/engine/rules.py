"""Declarative template rules (Part 3.1) — a family's checks written as data.

A template may carry `rules` (on the grid, or on the template data): a list of
small objects, each naming a check the coded validators would otherwise have
to know. They run through the same registry as every coded check
(validators.py) and are applied by the same three rules — FAIL makes each
affected value exactly `low`, UNREADABLE adds a reason and moves no level, PASS
is evidence only — so a rule cannot claim more than a coded check can.

    {"name": "lines_sum", "type": "sum_equals",
     "terms": ["items.Amount"], "total": "Subtotal"}

REFERENCES. A value is named by the template's own words:
  `Subtotal`            the field slot whose label is "Subtotal" (case and
                        spacing ignored); a cell ref (`B7`) also works
  `items.Amount`        the column headed "Amount" of the table named "items"
                        (its rows); a table is also found by its header text
  `-Discount`           in `terms`: subtract (the magnitude, as the invoice
                        check does with a printed discount)
  `Tax?`                optional: an EMPTY optional value counts as nothing;
                        an empty required value means the rule does not run
                        (use `required_if` to demand a value)

TYPES
  sum_equals    terms -> total; a column term sums its rows. Tolerance: one
                cent per summed amount (as the coded line check), or `tolerance`.
                A value with no digit in it ("aaaaaa") FAILS the rule; an
                ambiguous figure ("1,234") makes it UNREADABLE
  equals        left == right: as amounts when both are amounts, else as text
                (case and spacing ignored)
  product       factors multiply to result; with a column it runs PER ROW
  range         min <= value <= max; per row for a column
  regex         the value matches `pattern` in full; per row for a column
  id_type       the value passes the identifier plug-in `id_type`
                (engine/identifiers); per row for a column
  date_order    `first` is on or before `then` (`strict`: before)
  count_matches the table `table` has as many rows as the field `count` says
  currency_same every amount in `values` is in one currency
  required_if   `value` must not be empty when `if` is filled (and, with
                `equals`, holds that text)

Reason codes: `rule_failed:<name>` on FAIL, `rule_unreadable:<name>` when the
values are present but cannot be read as the rule needs (an amount that is
ambiguous, a date that could be either order). A rule the template states
wrongly (unknown type, a reference to nothing, a bad pattern) is never skipped
quietly: it is UNREADABLE `rule_unreadable:<name>` with a note, and
`rule_problems` reports it when the template is saved.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from validators import ANY, FAIL, PASS, UNREADABLE, CheckResult, register

CENT = Decimal("0.01")
RULE_FAILED, RULE_UNREADABLE = "rule_failed", "rule_unreadable"
TYPES = ("sum_equals", "equals", "product", "range", "regex", "id_type",
         "date_order", "count_matches", "currency_same", "required_if")
#: the keys each type needs, beyond name and type
_NEEDS = {"sum_equals": ("terms", "total"), "equals": ("left", "right"),
          "product": ("factors", "result"), "range": ("value",),
          "regex": ("value", "pattern"), "id_type": ("value", "id_type"),
          "date_order": ("first", "then"), "count_matches": ("table", "count"),
          "currency_same": ("values",), "required_if": ("value", "if")}


def _norm(s):
    return re.sub(r"\s+", " ", str(s or "")).strip().casefold()


#: the largest tolerance a rule may state. A tolerance exists to absorb
#: rounding; one wider than this would let unequal values pass, which is the
#: rule failing open (Review-3 F4).
MAX_TOLERANCE = Decimal(1000)


def _number_problem(rule, key):
    """Why `rule[key]` is not a usable number, or None. NaN raised inside a
    comparison and Infinity passed every unequal pair, so both are refused
    here, at save time, rather than met at run time."""
    raw = rule.get(key)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return f"{key} must be a number, not {raw!r}"
    try:
        d = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return f"{key} must be a number, not {raw!r}"
    if not d.is_finite():
        return f"{key} must be a finite number, not {raw!r}"
    if key == "tolerance" and d < 0:
        return f"tolerance cannot be negative ({raw!r})"
    if key == "tolerance" and d > MAX_TOLERANCE:
        return f"tolerance {raw!r} is wider than {MAX_TOLERANCE} and would pass unequal values"
    return None


def rules_of(template_data):
    """The template's declared rules: `rules` on the template data, else on
    its grid (`layout`). Always a list."""
    td = template_data if isinstance(template_data, dict) else {}
    grid = td.get("layout") if isinstance(td.get("layout"), dict) else td
    rules = td.get("rules") or grid.get("rules") or []
    # A malformed entry is KEPT so it is reported (rule_problems at save,
    # UNREADABLE at run time), never dropped quietly (Review-3 F4).
    return list(rules) if isinstance(rules, list) else [rules]


# ── references ─────────────────────────────────────────────────────────────

class _Ref:
    """One resolved reference: a field (`ref`) or a table column (`table`,
    `key`). `sign` is -1 for a subtracted term; `optional` for `X?`."""

    def __init__(self, text, field=None, table=None, key=None):
        self.text, self.field, self.table, self.key = text, field, table, key
        self.sign, self.optional = 1, False

    @property
    def is_column(self):
        return self.table is not None


def _resolve(spec, fields, tables):
    s = str(spec or "").strip()
    sign, optional = 1, False
    if s.startswith("-"):
        sign, s = -1, s[1:].strip()
    if s.endswith("?"):
        optional, s = True, s[:-1].strip()
    out = None
    if "." in s:
        tname, col = (p.strip() for p in s.split(".", 1))
        for t in tables or []:
            if _norm(t.get("name")) == _norm(tname) or _norm(t.get("title")) == _norm(tname):
                # a transposed table answers by its `fields`; either way the
                # row key is the column's key, else its header (table_headers)
                for c in (t.get("columns") or []) + (t.get("fields") or []):
                    key = c.get("key") or c.get("header")
                    if _norm(c.get("header")) == _norm(col) or _norm(key) == _norm(col):
                        out = _Ref(spec, table=t["name"], key=key)
                        break
            if out:
                break
    if out is None:
        ref_like = re.fullmatch(r"[A-Za-z]{1,3}\d+", s)
        for f in fields or []:
            if (ref_like and str(f.get("ref", "")).upper() == s.upper()) \
                    or _norm(f.get("row_label")) == _norm(s):
                out = _Ref(spec, field=f)
                break
    if out is not None:
        out.sign, out.optional = sign, optional
    return out


def _problems(rule, fields, tables):
    """What is wrong with one rule as the template states it ([] = fine)."""
    from identifiers import known_types
    from safe_regex import pattern_problem
    if not isinstance(rule, dict):
        return [f"a rule must be an object with a name and a type, not {rule!r:.60}"]
    name = rule.get("name") or "(unnamed)"
    kind = rule.get("type")
    if kind not in TYPES:
        return [f"rule {name}: unknown type {kind!r} (one of {', '.join(TYPES)})"]
    missing = [k for k in _NEEDS[kind] if rule.get(k) in (None, "", [])]
    if missing:
        return [f"rule {name}: {kind} needs {', '.join(missing)}"]
    out = []
    specs = []
    for k in ("terms", "factors", "values"):
        specs += list(rule.get(k) or []) if isinstance(rule.get(k), list) else []
    specs += [rule.get(k) for k in ("total", "left", "right", "result", "value",
                                    "first", "then", "count", "if") if rule.get(k)]
    for sp in specs:
        if _resolve(sp, fields, tables) is None:
            out.append(f"rule {name}: {sp!r} names no field or table column of this template")
    if kind == "count_matches" and not any(
            _norm(t.get("name")) == _norm(rule["table"]) for t in tables or []):
        out.append(f"rule {name}: no table named {rule['table']!r}")
    if kind == "regex":
        why = pattern_problem(rule["pattern"])
        if why:
            out.append(f"rule {name}: {why}")
    for k in ("tolerance", "min", "max"):
        why = _number_problem(rule, k)
        if why:
            out.append(f"rule {name}: {why}")
    if kind == "id_type" and str(rule["id_type"]).lower() not in known_types():
        out.append(f"rule {name}: unknown id_type {rule['id_type']!r}")
    if kind == "range" and rule.get("min") is None and rule.get("max") is None:
        out.append(f"rule {name}: range needs min or max")
    if not str(rule.get("name") or "").strip():
        out.append("a rule has no name (the name is its reason code)")
    return out


def rule_problems(rules, fields, tables):
    """Every problem with a template's declared rules, for the template gate
    (`POST /api/templates/shape`) and the run itself."""
    out, names = [], set()
    if rules is not None and not isinstance(rules, list):
        return [f"rules must be a list of rules, not {type(rules).__name__}"]
    for r in rules or []:
        out += _problems(r, fields, tables)
        if not isinstance(r, dict):
            continue
        n = str(r.get("name") or "").strip()
        if n and n in names:
            out.append(f"rule {n}: two rules share this name (it is the reason code)")
        names.add(n)
    return out


# ── reading values ─────────────────────────────────────────────────────────

def _field_text(ctx, ref):
    return str((ctx.values or {}).get(ref.field["ref"]) or "").strip()


def _rows(ctx, ref):
    """[(slot id, cell text)] for a column reference's non-empty cells."""
    rows = (ctx.rows or {}).get(ref.table) or []
    return [(f"{ref.table}_rows[{i}]", str(r.get(ref.key) or "").strip())
            for i, r in enumerate(rows)
            if isinstance(r, dict) and str(r.get(ref.key) or "").strip()]


def _money(text):
    from amounts import money
    return money(text)


def _result(rule, status, slots, said="", evidence=None, review=False):
    name = rule["name"]
    reason = {FAIL: f"{RULE_FAILED}:{name}",
              UNREADABLE: f"{RULE_UNREADABLE}:{name}"}.get(status, "")
    return CheckResult(
        f"rule:{name}", status, list(dict.fromkeys(slots)), reason,
        evidence=evidence or {},
        flags=[(name, "", said)] if said and status != PASS else [],
        notes=[f"rule {name}: {said}"] if said and status != PASS else [],
        # one key per rule: the record's `validation` is merged with update()
        validation={f"rule:{name}": status},
        needs_review=review or status != PASS)


# ── the types ──────────────────────────────────────────────────────────────

def _sum_equals(rule, ctx, R):
    total = R(rule["total"])
    if total.is_column:
        return [_result(rule, UNREADABLE, [], "the total must be a field, not a column")]
    terms = [R(t) for t in rule["terms"]]
    if any(t.is_column and t.table in (ctx.incomplete or ()) for t in terms):
        return []      # rows were dropped (already flagged): the sum cannot reach
    slots, amounts, unreadable = [], [], []
    ttext = _field_text(ctx, total)
    if not ttext:
        return []
    for t in terms:
        if t.is_column:
            cells = _rows(ctx, t)
            if not cells:
                if t.optional:
                    continue
                return []
            for sid, txt in cells:
                slots.append(sid)
                v = _money(txt)
                (unreadable.append(t.text) if v is None
                 else amounts.append(-abs(v) if t.sign < 0 else v))
        else:
            txt = _field_text(ctx, t)
            if not txt:
                if t.optional:
                    continue
                return []
            slots.append(t.field["ref"])
            v = _money(txt)
            (unreadable.append(t.text) if v is None
             else amounts.append(-abs(v) if t.sign < 0 else v))
    slots.append(total.field["ref"])
    want = _money(ttext)
    if want is None:
        unreadable.append(total.text)
    # NOT AN AMOUNT AT ALL (Part 3.4 e): a value in the sum with no digit in
    # it ("aaaaaa", "see attached") is wrong, not ambiguous — the rule FAILS
    # and the values go low. An ambiguous figure ("1,234") stays UNREADABLE.
    texts = [_field_text(ctx, t) for t in terms if not t.is_column] + [ttext]
    texts += [txt for t in terms if t.is_column for _sid, txt in _rows(ctx, t)]
    junk = [x for x in texts if x and not any(ch.isdigit() for ch in x)]
    if junk:
        return [_result(rule, FAIL, slots,
                        f"{', '.join(repr(x) for x in dict.fromkeys(junk))} is not an amount")]
    if unreadable:
        return [_result(rule, UNREADABLE, slots,
                        f"{', '.join(dict.fromkeys(unreadable))} is not a plain amount")]
    got = sum(amounts, Decimal(0))
    n_col = sum(1 for t in terms if t.is_column)
    tol = Decimal(str(rule["tolerance"])) if rule.get("tolerance") is not None \
        else (CENT * len(amounts) if n_col else CENT)
    ok = abs(got - want) <= tol
    return [_result(rule, PASS if ok else FAIL, slots,
                    "" if ok else f"the terms come to {got}, not {want}")]


def _equals(rule, ctx, R):
    a, b = R(rule["left"]), R(rule["right"])
    if a.is_column or b.is_column:
        return [_result(rule, UNREADABLE, [], "equals compares two fields")]
    ta, tb = _field_text(ctx, a), _field_text(ctx, b)
    if not ta or not tb:
        return []
    slots = [a.field["ref"], b.field["ref"]]
    va, vb = _money(ta), _money(tb)
    if va is not None and vb is not None:
        ok = abs(va - vb) <= Decimal(str(rule.get("tolerance", CENT)))
    else:
        ok = _norm(ta) == _norm(tb)
    return [_result(rule, PASS if ok else FAIL, slots,
                    "" if ok else f"{a.text} reads {ta!r}, {b.text} reads {tb!r}")]


def _per_row_or_field(rule, ctx, refs):
    """Rows to evaluate: [(slots, {ref.text: text})]. Column references are
    read row by row (one table); field references are the same on every row."""
    cols = [r for r in refs if r.is_column]
    tables = {r.table for r in cols}
    if len(tables) > 1:
        return None
    if not cols:
        vals = {r.text: _field_text(ctx, r) for r in refs}
        return [([r.field["ref"] for r in refs], vals)]
    if cols[0].table in (ctx.incomplete or ()):
        return []
    out = []
    for i, row in enumerate((ctx.rows or {}).get(cols[0].table) or []):
        if not isinstance(row, dict):
            continue
        vals, slots = {}, [f"{cols[0].table}_rows[{i}]"]
        for r in refs:
            if r.is_column:
                vals[r.text] = str(row.get(r.key) or "").strip()
            else:
                vals[r.text] = _field_text(ctx, r)
                slots.append(r.field["ref"])
        out.append((slots, vals))
    return out


def _product(rule, ctx, R):
    refs = [R(f) for f in rule["factors"]] + [R(rule["result"])]
    units = _per_row_or_field(rule, ctx, refs)
    if units is None:
        return [_result(rule, UNREADABLE, [], "product reads one table at a time")]
    out = []
    for slots, vals in units:
        if any(not vals[r.text] for r in refs if not r.optional):
            continue
        nums = [_money(vals[r.text]) for r in refs]
        if None in nums:
            out.append(_result(rule, UNREADABLE, slots, "a factor or the result is not a plain amount"))
            continue
        got = Decimal(1)
        for n in nums[:-1]:
            got *= n
        tol = Decimal(str(rule.get("tolerance", CENT)))
        ok = abs(got - nums[-1]) <= tol
        out.append(_result(rule, PASS if ok else FAIL, slots,
                           "" if ok else f"{' × '.join(str(n) for n in nums[:-1])} = {got}, not {nums[-1]}"))
    return out


def _single_value(rule, ctx, R, test):
    ref = R(rule["value"])
    units = _per_row_or_field(rule, ctx, [ref])
    out = []
    for slots, vals in units or []:
        txt = vals[ref.text]
        if not txt:
            continue
        status, said = test(txt)
        out.append(_result(rule, status, slots, said))
    return out


def _range(rule, ctx, R):
    lo = None if rule.get("min") is None else Decimal(str(rule["min"]))
    hi = None if rule.get("max") is None else Decimal(str(rule["max"]))

    def test(txt):
        v = _money(txt)
        if v is None:
            return UNREADABLE, f"{txt!r} is not a plain number"
        ok = (lo is None or v >= lo) and (hi is None or v <= hi)
        return (PASS, "") if ok else (FAIL, f"{v} is outside {lo if lo is not None else '…'}–{hi if hi is not None else '…'}")
    return _single_value(rule, ctx, R, test)


def _regex(rule, ctx, R):
    from safe_regex import Budget, compile_safe, too_long
    pat = compile_safe(rule["pattern"])
    budget = Budget()

    def test(txt):
        if too_long(txt):
            return UNREADABLE, "the value is too long to check against a pattern"
        ok = budget.run(pat.fullmatch, txt)
        return (PASS, "") if ok else (FAIL, f"{txt!r} does not have the declared form")
    return _single_value(rule, ctx, R, test)


def _id_type(rule, ctx, R):
    from identifiers import validate

    def test(txt):
        v = validate(rule["id_type"], txt)
        if v.ok is None:
            return UNREADABLE, f"{txt!r} holds no {rule['id_type']}"
        return (PASS, "") if v.ok else (FAIL, f"{txt!r} is not a valid {rule['id_type']}"
                                        + (f" ({v.note})" if getattr(v, "note", "") else ""))
    return _single_value(rule, ctx, R, test)


def _date_order(rule, ctx, R):
    from dates import document_order, parse_date
    a, b = R(rule["first"]), R(rule["then"])
    if a.is_column or b.is_column:
        return [_result(rule, UNREADABLE, [], "date_order compares two fields")]
    ta, tb = _field_text(ctx, a), _field_text(ctx, b)
    if not ta or not tb:
        return []
    order, _how = document_order(ctx.texts(), ctx.locale)
    da, db = parse_date(ta, order), parse_date(tb, order)
    slots = [a.field["ref"], b.field["ref"]]
    if da.value is None or db.value is None or da.ambiguous or db.ambiguous:
        return [_result(rule, UNREADABLE, slots, "a date cannot be read without guessing its order")]
    ok = da.value < db.value if rule.get("strict") else da.value <= db.value
    return [_result(rule, PASS if ok else FAIL, slots,
                    "" if ok else f"{a.text} ({da.value}) is not before {b.text} ({db.value})")]


def _count_matches(rule, ctx, R):
    t = next(t for t in ctx.tables or [] if _norm(t.get("name")) == _norm(rule["table"]))
    cnt = R(rule["count"])
    txt = _field_text(ctx, cnt)
    if not txt:
        return []
    if t["name"] in (ctx.incomplete or ()):
        return []
    rows = [i for i, r in enumerate((ctx.rows or {}).get(t["name"]) or [])
            if isinstance(r, dict) and any(str(v).strip() for k, v in r.items()
                                            if not str(k).startswith("_"))]
    m = re.fullmatch(r"\s*(\d+)\s*", txt)
    if not m:
        return [_result(rule, UNREADABLE, [cnt.field["ref"]], f"{txt!r} is not a count")]
    ok = int(m.group(1)) == len(rows)
    return [_result(rule, PASS if ok else FAIL, [cnt.field["ref"]],
                    "" if ok else f"the document says {m.group(1)}; {len(rows)} row(s) were read")]


def _currency_same(rule, ctx, R):
    from amounts import CURRENCY_MISMATCH, currency_agreement
    slots, texts = [], []
    for spec in rule["values"]:
        ref = R(spec)
        if ref.is_column:
            for sid, txt in _rows(ctx, ref):
                slots.append(sid)
                texts.append(txt)
        elif _field_text(ctx, ref):
            slots.append(ref.field["ref"])
            texts.append(_field_text(ctx, ref))
    if len(texts) < 2:
        return []
    verdict, named = currency_agreement(texts)
    if verdict == "ok":
        return [_result(rule, PASS, slots)]
    return [_result(rule, FAIL if verdict == CURRENCY_MISMATCH else UNREADABLE, slots,
                    f"the amounts are in {'different currencies' if verdict == CURRENCY_MISMATCH else 'currencies that may differ'} ({', '.join(named)})")]


def _required_if(rule, ctx, R):
    val, cond = R(rule["value"]), R(rule["if"])
    if val.is_column or cond.is_column:
        return [_result(rule, UNREADABLE, [], "required_if names two fields")]
    ctext = _field_text(ctx, cond)
    holds = bool(ctext) and (rule.get("equals") is None
                             or _norm(ctext) == _norm(rule["equals"]))
    if not holds or _field_text(ctx, val):
        return [_result(rule, PASS, [val.field["ref"]])] if holds else []
    # The required value is EMPTY: there is no value to mark low, so the
    # finding sits on the value that demanded it and the record goes to review.
    return [_result(rule, FAIL, [cond.field["ref"]],
                    f"{val.text} is empty, and {cond.text} reads {ctext!r}", review=True)]


_RUN = {"sum_equals": _sum_equals, "equals": _equals, "product": _product,
        "range": _range, "regex": _regex, "id_type": _id_type,
        "date_order": _date_order, "count_matches": _count_matches,
        "currency_same": _currency_same, "required_if": _required_if}


def run_rules(rules, ctx):
    """Every declared rule's results for one record."""
    out = []
    if not isinstance(rules, list):
        rules = [rules] if rules else []
    for rule in rules:
        if not isinstance(rule, dict):
            out.append(_result({"name": "(malformed)"}, UNREADABLE, [],
                               "; ".join(_problems(rule, ctx.fields, ctx.tables))
                               + " — not checked"))
            continue
        name = str(rule.get("name") or "").strip() or "(unnamed)"
        rule = {**rule, "name": name}
        bad = _problems(rule, ctx.fields, ctx.tables)
        if bad:
            out.append(_result(rule, UNREADABLE, [], "; ".join(bad) + " — not checked"))
            continue

        def R(spec):
            return _resolve(spec, ctx.fields, ctx.tables)
        # ONE rule that cannot run never takes the others (or the record)
        # down: it is UNREADABLE, said on the record, and the record goes to
        # review — a time budget spent included.
        try:
            out += _RUN[rule["type"]](rule, ctx, R)
        except Exception as exc:
            out.append(_result(rule, UNREADABLE, [],
                               f"could not run ({type(exc).__name__}: {exc}) — not checked"))
    return out


def declared_rules(ctx):
    """The ANY-family validator: whatever rules the template declared."""
    return run_rules(getattr(ctx, "rules", None) or [], ctx)


register(ANY, declared_rules)
