"""
Adapter: engine output -> the flat gold-label shape.

This is the ONLY place that knows the engine's output schema. When the
engine's output changes, this file changes — never the label files in
tests/gold/labels/.

Input: the list of DocumentExtractionResult the pipeline returns for one file
(each has .extracted_data). Output:

    {"fields": {gold_field_name: value},
     "tables": {gold_table_name_or_pred_name: [ {gold_col: value} ]},
     "notes":  [strings worth surfacing in the report]}

Engine output shapes handled (see CLAUDE.md / audit §2):
  - extracted_data["extracted_data"]: {label: {value, confidence, ref}} or
    {label: value} — the per-label form fields.
  - extracted_data["extracted_fields"]: {cell_ref: value} — resolved to label
    names via the template grid (label cell to the left of / above the ref).
  - extracted_data["layout_sections"]: {slug: {rows: [{label, value, ...}]}}
    — the structural path. Sections are matched to gold table names
    (exact -> substring -> token overlap); rows become gold-schema rows with
    the label in the gold table's first string column and the value in its
    last money/number column. Two pred sections matching the same gold table
    are MERGED (mirroring the layout writer), so a phantom duplicate section
    shows up as hallucinated rows instead of disappearing.
  - extracted_data["table_rows"] / any "*_rows" list — matched to gold tables
    by key name; row keys matched to gold column names case-insensitively.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from tests.harness.scoring import is_empty

_SKIP_KEYS = {"extracted_data", "extracted_fields", "layout_sections",
              "validation", "template_regions", "template_type",
              "overall_confidence", "binding_column_groups", "document_type",
              "raw_llm_responses", "unguided_content"}


# ── widening switches ────────────────────────────────────────────────────────
# Every mapping rule looser than "the names are the same" lives behind one of
# these, so the harness reports the ADAPTED number and the RAW number (all off)
# side by side in every run.
#
# Three earlier rules — identify a table by its row content, map leftover
# columns by position, and "if gold has one table, anything unmatched is it" —
# were replaced by a single ELIMINATION rule. Those three expressed a
# preference; elimination only fires when the correspondence is forced, with
# exactly one unmatched candidate on each side. It measures the same 97.9%.
WIDENINGS = {
    "W1_fuzzy_names": True,      # exact -> UNAMBIGUOUS substring / token overlap
    "W4_kv_rows_as_fields": True,
    "E_elimination": True,       # a correspondence that is forced, not preferred
}


def set_widenings(**kw):
    """Enable/disable widenings. Returns the previous state (for restore)."""
    prev = dict(WIDENINGS)
    WIDENINGS.update(kw)
    return prev


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").casefold())


def _tokens(s: Any) -> set:
    return set(re.findall(r"[a-z0-9]+", str(s or "").casefold()))


def _match_name(pred_name: str, gold_names: list) -> Optional[str]:
    """exact (normalized) -> substring -> token overlap >= 0.5."""
    pn = _norm(pred_name)
    if not pn:
        return None
    for g in gold_names:
        if _norm(g) == pn:
            return g
    if not WIDENINGS["W1_fuzzy_names"]:
        return None

    # A fuzzy match must be UNAMBIGUOUS. Where two gold names fit equally well,
    # there is no evidence for either, and picking the first one is leniency
    # dressed as a match — "Total" fit "Total Earnings" and "Total Deductions"
    # exactly as well, and iteration order decided it. Ambiguity now means no
    # match, which scores as missed rather than as a coin-flip correct.
    subs = [g for g in gold_names
            if len(_norm(g)) >= 4 and len(pn) >= 4
            and (_norm(g) in pn or pn in _norm(g))]
    if len(subs) == 1:
        return subs[0]
    if len(subs) > 1:
        return None

    pt = _tokens(pred_name)
    scored = []
    for g in gold_names:
        gt = _tokens(g)
        if not gt or not pt:
            continue
        scored.append((len(gt & pt) / len(gt | pt), g))
    if not scored:
        return None
    best_score = max(s for s, _ in scored)
    if best_score < 0.5:
        return None
    tied = [g for s, g in scored if s == best_score]
    return tied[0] if len(tied) == 1 else None


def _cell_value(v: Any) -> Any:
    if isinstance(v, dict):
        return v.get("value")
    return v


def _ref_to_rc(ref: str) -> Optional[tuple]:
    m = re.fullmatch(r"([A-Za-z]+)(\d+)", str(ref).strip())
    if not m:
        return None
    col = 0
    for ch in m.group(1).upper():
        col = col * 26 + (ord(ch) - 64)
    return int(m.group(2)) - 1, col - 1  # 0-based (row, col)


def _grid_lookup(grid: dict) -> dict:
    """cells '{r},{c}' -> value string."""
    out = {}
    for key, cell in (grid or {}).get("cells", {}).items():
        try:
            r, c = map(int, key.split(","))
        except (ValueError, AttributeError):
            continue
        out[(r, c)] = (cell or {}).get("value", "") or ""
    return out


def _label_for_ref(ref: str, grid_cells: dict) -> Optional[str]:
    rc = _ref_to_rc(ref)
    if rc is None:
        return None
    r, c = rc
    for cc in range(c - 1, -1, -1):  # nearest non-empty cell to the left
        v = grid_cells.get((r, cc), "")
        if str(v).strip():
            return str(v).strip()
    for rr in range(r - 1, max(-1, r - 4), -1):  # else scan up
        v = grid_cells.get((rr, c), "")
        if str(v).strip():
            return str(v).strip()
    return None


def _gold_label_value_cols(gold_table_name: str, label: dict) -> tuple:
    """(label_col, value_col) for mapping structural {label, value} rows into
    a gold table's schema: first string column, last money/number column."""
    types = (label.get("table_types", {}) or {}).get(gold_table_name, {})
    rows = (label.get("tables", {}) or {}).get(gold_table_name, [])
    cols = list(types.keys()) or (list(rows[0].keys()) if rows else [])
    label_col = next((c for c in cols if types.get(c, "string") == "string"),
                     cols[0] if cols else "Label")
    numeric = [c for c in cols if types.get(c) in ("money", "number")]
    value_col = numeric[-1] if numeric else (cols[-1] if cols else "Value")
    return label_col, value_col


def adapt(results: list, label: dict, template_grid: dict) -> dict:
    """Convert the pipeline's result list for one file into the flat shape."""
    notes = []
    fields = {}
    tables = {}
    gold_field_names = list((label.get("fields") or {}).keys())
    gold_table_names = list((label.get("tables") or {}).keys())
    grid_cells = _grid_lookup(template_grid)

    if len(results) > 1:
        notes.append(f"engine returned {len(results)} result blocks for one "
                     f"document; fields merged (first wins), tables concatenated")

    def put_field(name, value):
        if is_empty(value):
            return
        g = _match_name(name, gold_field_names)
        key = g or str(name)
        if key not in fields:
            fields[key] = value

    def put_table(name, rows):
        g = _match_name(name, gold_table_names)
        key = g or str(name)
        tables.setdefault(key, []).extend(rows)
        if g is None and rows:
            notes.append(f"extracted table/section '{name}' matches no gold "
                         f"table — all its rows will score as hallucinated")

    for r in results:
        ed = getattr(r, "extracted_data", None) or {}
        if not isinstance(ed, dict):
            continue

        # 1. per-label form fields
        inner = ed.get("extracted_data")
        if isinstance(inner, dict):
            for name, v in inner.items():
                if str(name).startswith("_"):
                    continue
                put_field(name, _cell_value(v))

        # 2. cell-ref keyed fields -> labels via the template grid
        ef = ed.get("extracted_fields")
        if isinstance(ef, dict):
            for ref, v in ef.items():
                val = _cell_value(v)
                if is_empty(val):
                    continue
                lbl = _label_for_ref(ref, grid_cells)
                if lbl:
                    put_field(lbl, val)
                else:
                    notes.append(f"extracted_fields[{ref}]={val!r} has no "
                                 f"resolvable label in the template grid")

        # 3. structural layout sections -> tables (label/value pairs)
        ls = ed.get("layout_sections")
        if isinstance(ls, dict):
            for slug, block in ls.items():
                rows = (block or {}).get("rows", []) if isinstance(block, dict) else []
                g = _match_name(slug, gold_table_names)
                if g:
                    lc, vc = _gold_label_value_cols(g, label)
                else:
                    lc, vc = "Label", "Value"
                out_rows = []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    lbl, val = row.get("label"), row.get("value")
                    if is_empty(lbl) and is_empty(val):
                        continue
                    out_rows.append({lc: lbl, vc: val})
                if out_rows:
                    put_table(slug, out_rows)

        # 4. table_rows / *_rows arrays -> tables (column-name keyed)
        for key, val in ed.items():
            if key in _SKIP_KEYS or not isinstance(val, list):
                continue
            if not (key == "table_rows" or key.endswith("_rows")):
                continue
            base = key[:-5] if key.endswith("_rows") else key
            raw_rows = [row for row in val if isinstance(row, dict)]
            if not raw_rows:
                continue

            # Identify the gold table BEFORE mapping columns. The vocabulary to
            # map column names into is a property of the table, so the table has
            # to be known first: by name, then by the rows it actually holds,
            # then — only if gold describes a single table — by elimination.
            g = _match_name(base, gold_table_names)
            if g is None and WIDENINGS["E_elimination"]:
                # ELIMINATION. Exactly one unmatched predicted table and exactly
                # one unmatched gold table can only correspond to each other —
                # there is no other candidate for either. This is a forced
                # correspondence, not a preferred one: with two of anything
                # unmatched it does not fire at all.
                free_gold = [t for t in gold_table_names if t not in tables]
                n_pred = sum(1 for k in ed
                             if isinstance(ed.get(k), list) and k not in _SKIP_KEYS
                             and (k == "table_rows" or k.endswith("_rows")))
                if len(free_gold) == 1 and n_pred == 1:
                    g = free_gold[0]
                    notes.append(f"table '{base}' -> gold table '{g}' by "
                                 f"elimination (one unmatched on each side)")
            cols = list((label.get("table_types", {}) or {}).get(g, {}).keys()) if g else []

            out_rows = []
            for row in raw_rows:
                pred_keys = [k for k in row if not str(k).startswith("_")]
                by_name, used = {}, set()
                for ck in pred_keys:                       # 1. by name
                    gc = _match_name(ck, [c for c in cols if c not in used]) if cols else None
                    if gc:
                        by_name[ck] = gc
                        used.add(gc)
                # 2. ELIMINATION, same rule as for tables. A band's label
                #    column is headed with the template's own text ("CURRENT
                #    ASSETS") where the labels call it "Label", so no name match
                #    is possible — but if it is the only unmatched column on
                #    each side, it is the only thing it can be. Two unmatched on
                #    either side and this does not fire.
                free = [c for c in cols if c not in used]
                unmatched = [ck for ck in pred_keys if ck not in by_name]
                if (WIDENINGS["E_elimination"]
                        and len(free) == 1 and len(unmatched) == 1):
                    by_name[unmatched[0]] = free[0]
                mapped = {by_name.get(ck, str(ck)): _cell_value(row[ck])
                          for ck in pred_keys}
                if any(not is_empty(v) for v in mapped.values()):
                    out_rows.append(mapped)
            if out_rows:
                put_table(g or base, out_rows)

    # A list of labelled amounts can legitimately be described EITHER as named
    # fields (a hand-built template names each row) OR as a two-column table of
    # label/value rows (shape inference usually does, and an income statement
    # genuinely is a list of labelled amounts). They are the same thing on a
    # sheet. Where a predicted table matched no gold table and its rows carry
    # gold FIELD names, those rows are those fields.
    #
    # This cannot hide an error: a row whose label does NOT match a gold field
    # stays a table row and still scores as hallucinated, and a row with the
    # right label but the wrong value becomes a field scored `wrong`.
    for tname in ([t for t in list(tables) if t not in gold_table_names]
                  if WIDENINGS["W4_kv_rows_as_fields"] else []):
        rows = tables.get(tname) or []
        cols = [c for c in (rows[0].keys() if rows else [])
                if not str(c).startswith("_")]
        if len(cols) != 2:
            continue
        label_col, value_col = cols
        kept, moved = [], 0
        for row in rows:
            g = _match_name(row.get(label_col), gold_field_names)
            if g and g not in fields and not is_empty(row.get(value_col)):
                fields[g] = row.get(value_col)
                moved += 1
            else:
                kept.append(row)
        if moved:
            notes.append(f"{moved} label/value row(s) from table '{tname}' "
                         f"scored as the gold fields they name")
            if kept:
                tables[tname] = kept
            else:
                del tables[tname]

    return {"fields": fields, "tables": tables, "notes": notes}
