"""Categorization of table rows (Part A2): rules first, a model only as a
fallback, and never written into an extracted value.

RULES, in order — the first layer with ANY hit decides:

  1. the template's own (`categories` on the template grid),
  2. the firm's (`categories:` in the firm's schema YAML),
  3. a small generic default list.

A rule is {"category": "Travel", "keywords": ["airline", "taxi"],
"regex": ["^UBER\\\\b"]}. Keywords match as whole words or phrases,
case-insensitively; a regex is used as written (case-insensitive). The row's
TEXT cells are matched (amount and date columns are not text).

THE RESULT CARRIES ITS LEVEL:

  one category's rule matched           grounded, `by: rule`, the rule and words
  rules of SEVERAL categories matched   "Uncategorized", reason category_uncertain
                                        (an ambiguous merchant: "Uber Eats")
  no rule matched, model allowed        the model's answer if it names a listed
                                        category: unverified, `by: model`
  otherwise / model unavailable         "Uncategorized", category_uncertain

Stored beside the rows (`categories: {table: [{row, category, level, by,
rule, matched, reasons}]}`), never into them: a category is the engine's
opinion about a row, not something the document printed.
"""
from __future__ import annotations

import json
import re

from safe_regex import MAX_INPUT

UNCATEGORIZED = "Uncategorized"
CATEGORY_UNCERTAIN = "category_uncertain"

DEFAULT_RULES = [
    {"category": "Travel", "keywords": ["airline", "airlines", "flight", "airfare", "taxi",
                                        "uber", "lyft", "train", "railway", "car rental", "parking", "toll"]},
    {"category": "Lodging", "keywords": ["hotel", "inn", "motel", "lodging", "airbnb", "resort"]},
    {"category": "Meals", "keywords": ["restaurant", "cafe", "coffee", "catering", "meal", "meals",
                                       "lunch", "dinner", "breakfast", "eats"]},
    {"category": "Office Supplies", "keywords": ["stationery", "office supplies", "printer paper",
                                                 "toner", "pens"]},
    {"category": "Software", "keywords": ["software", "subscription", "license", "licence", "saas",
                                          "cloud hosting"]},
    {"category": "Utilities", "keywords": ["electricity", "electric", "water bill", "gas bill",
                                           "internet", "broadband", "telephone", "mobile"]},
    {"category": "Rent", "keywords": ["rent", "lease"]},
    {"category": "Insurance", "keywords": ["insurance", "premium", "policy"]},
    {"category": "Salary", "keywords": ["salary", "payroll", "wages"]},
    {"category": "Tax", "keywords": ["tax", "vat", "gst", "duty"]},
    {"category": "Bank Charges", "keywords": ["bank charge", "bank charges", "service charge",
                                              "fee", "fees", "interest charged"]},
    {"category": "Professional Fees", "keywords": ["consulting", "legal", "audit", "accounting",
                                                   "professional fees"]},
]

_NOT_TEXT = re.compile(r"amount|debit|credit|balance|total|qty|quantity|rate|price|"
                       r"date|tax|vat|gst|no\b|number|#", re.I)


def _row_text(row: dict) -> str:
    parts = []
    for k, v in row.items():
        if str(k).startswith("_") or v is None:
            continue
        s = str(v).strip()
        if not s or _NOT_TEXT.search(str(k)) or re.fullmatch(r"[\d\s.,$€£₹¥()+\-/%]*", s):
            continue
        parts.append(s)
    return " ".join(parts)


def _compile(rules, refused=None):
    """[(category, [pattern])]. A regex outside the safe subset
    (engine/safe_regex.py) is refused in the editor; one that reaches a run
    anyway is left out and named in `refused`, never run (Review-3 F4)."""
    from safe_regex import UnsafePattern, compile_safe
    out = []
    for r in rules or [] if isinstance(rules, list) else []:
        if not isinstance(r, dict) or not str(r.get("category") or "").strip():
            continue
        pats = [re.compile(r"(?<!\w)" + re.escape(str(k).strip()) + r"(?!\w)", re.I)
                for k in r.get("keywords") or [] if str(k).strip()]
        for rx in r.get("regex") or []:
            try:
                pats.append(compile_safe(rx, re.I))
            except (UnsafePattern, re.error) as e:
                if refused is not None:
                    refused.append(f"the category pattern {str(rx)[:60]!r} "
                                   f"({r['category']}) was not used: {e}")
        if pats:
            out.append((str(r["category"]).strip(), pats))
    return out


def validate_rules(rules) -> list:
    """Plain-language problems with a rule list (for the editor)."""
    from safe_regex import pattern_problem
    problems = []
    if rules is not None and not isinstance(rules, list):
        return ["category rules must be a list"]
    for i, r in enumerate(rules or [], 1):
        if not isinstance(r, dict) or not str(r.get("category") or "").strip():
            problems.append(f"rule {i}: give it a category name")
            continue
        if not (r.get("keywords") or r.get("regex")):
            problems.append(f"rule {i} ({r['category']}): add at least one keyword or pattern")
        for rx in r.get("regex") or []:
            why = pattern_problem(rx)
            if why:
                problems.append(f"rule {i} ({r['category']}): the pattern {rx!r} is not valid: {why}")
    return problems


def _match(text, layer, budget=None):
    hits = {}
    text = text[:MAX_INPUT]
    for cat, pats in layer:
        for p in pats:
            m = budget.run(p.search, text) if budget else p.search(text)
            if m:
                hits.setdefault(cat, m.group(0))
                break
    return hits


def categorize_rows(rows, template_rules=None, firm_rules=None, model=None, allowed=None):
    """[{row, category, level, by, rule, matched, reasons}] for `rows`.

    `model(texts, categories) -> list[str] | None` is called once for the rows
    no rule decided, only when given. `allowed` is the category list a model
    answer must belong to (default: every category the rules name)."""
    from safe_regex import Budget, BudgetExceeded
    refused: list = []
    layers = [("template", _compile(template_rules, refused)),
              ("firm", _compile(firm_rules, refused)),
              ("default", _compile(DEFAULT_RULES))]
    budget = Budget()
    cats = list(allowed or dict.fromkeys(
        c for _n, layer in layers for c, _p in layer))
    out, pending = [], []
    for i, row in enumerate(rows or []):
        if not isinstance(row, dict):
            continue
        text = _row_text(row)
        entry = {"row": i, "category": UNCATEGORIZED, "level": "unverified", "by": "none",
                 "rule": "", "matched": "", "reasons": [CATEGORY_UNCERTAIN]}
        if refused:
            entry["note"] = "; ".join(refused)
        for name, layer in layers:
            try:
                hits = _match(text, layer, budget)
            except BudgetExceeded as e:
                entry["note"] = f"category rules not applied: {e}"
                break
            if len(hits) == 1:
                (cat, word), = hits.items()
                entry.update(category=cat, level="grounded", by="rule", rule=name,
                             matched=word, reasons=[])
                break
            if len(hits) > 1:
                entry["note"] = (f"{name} rules for several categories match "
                                 f"({', '.join(sorted(hits))}); not guessed")
                break
        else:
            if text:
                pending.append((entry, text))
        out.append(entry)
    if model and pending:
        try:
            answers = model([t for _e, t in pending], cats)
        except Exception:
            answers = None
        if not isinstance(answers, list):
            for e, _t in pending:
                e["note"] = "the model was unavailable; not categorized"
        else:
            for (e, _t), a in zip(pending, answers):
                a = str(a or "").strip()
                if a in cats:
                    e.update(category=a, level="unverified", by="model", reasons=[])
                else:
                    e["note"] = "the model's answer is not one of the listed categories"
    return out


def model_categorizer(orchestrator):
    """A `model` for categorize_rows that asks the provider once per call."""
    def ask(texts, categories):
        prompt = ("Assign a business category to each row below.\n"
                  f"Use ONLY these categories: {', '.join(categories)}.\n"
                  "If none fits, answer \"Uncategorized\".\n\n"
                  "Return ONLY a JSON object: {\"categories\": [\"cat1\", \"cat2\", ...]}\n"
                  "One category per row in the same order.\n\nRows:\n"
                  + "\n".join(f"Row {i + 1}: {json.dumps(t)}" for i, t in enumerate(texts[:50])))
        r = orchestrator.llm.extract(text="\n".join(texts[:50]), prompt=prompt)
        if not (r.success and isinstance(r.parsed_json, dict)):
            return None
        got = r.parsed_json.get("categories")
        return got if isinstance(got, list) else None
    return ask


__all__ = ["CATEGORY_UNCERTAIN", "DEFAULT_RULES", "UNCATEGORIZED", "categorize_rows",
           "model_categorizer", "validate_rules"]
