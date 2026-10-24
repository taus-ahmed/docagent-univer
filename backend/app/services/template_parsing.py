"""Template parsing and region analysis, the prompt registry loader, cell helpers.

Moved verbatim from app/api/routes/extract.py (round 13); extract.py re-exports every name.
"""

import app.services.paths  # noqa: F401  (engine on sys.path)
from app.models import ColumnTemplate
from typing import Optional
from pathlib import Path
from app.services.paths import _backend_dir
from app.services.paths import _engine_dir
from app.services.paths import _project_dir
from log_safety import exc_brief
import json
from log_safety import print_safe_traceback
import sys
# --imports-end--


def _compute_shape_for_grid(grid: dict) -> Optional[dict]:
    """Phase 2a — template shape from a grid. Safe to call from a request
    handler (the engine dir may not be on sys.path yet)."""
    for p in [str(_engine_dir), str(_backend_dir), str(_project_dir)]:
        if p not in sys.path:
            sys.path.insert(0, p)
    from template_shape import compute_shape
    return compute_shape(grid, log=lambda m: print(f"[SHAPE] {m}", flush=True))


def _parse_template(tpl: ColumnTemplate) -> Optional[dict]:
    """Parse a ColumnTemplate into extraction-ready format with region analysis."""
    if tpl.description:
        try:
            raw = json.loads(tpl.description)
            if isinstance(raw, dict) and "cells" in raw:
                template_data = {
                    "mode": "layout",
                    "layout": raw,
                    "doc_type": tpl.document_type or "other",
                    "name": tpl.name,
                }
                # Analyse regions once and cache in template_data
                try:
                    template_data["regions"] = _analyse_template_regions(raw)
                except Exception as region_err:
                    import traceback
                    print(f"[TEMPLATE] region analysis error: {exc_brief(region_err)}", flush=True)
                    print_safe_traceback()
                    # Fall back to empty regions so extraction can still proceed
                    template_data["regions"] = {
                        "primary_mode": "form_kv",
                        "explicit_targets": [],
                        "kv_pairs": [],
                        "two_col_pairs": [],
                        "table_regions": [],
                        "transposed_tables": [],
                        "section_label_rows": set(),
                        "has_explicit_targets": False,
                        "has_table": False,
                        "max_row": 0,
                        "max_col": 0,
                    }
                # Bug 5a: detect section-context risk for financial templates
                template_data["regions"]["needs_section_context"] = (
                    _detect_section_context_risk(
                        template_data["regions"], tpl.document_type or "other"
                    )
                )
                # Template shape, computed FRESH from the grid on every run.
                # It is a pure function of the grid and costs ~0.2 ms against a
                # multi-second model call, so there is nothing to gain by
                # storing it — and a stored copy can silently disagree with a
                # grid that changed, which is the failure this codebase already
                # had once with the template-understanding artifact.
                try:
                    shape = _compute_shape_for_grid(raw)
                    if shape:
                        template_data["shape"] = shape
                except Exception as shape_err:
                    print(f"[TEMPLATE] shape unavailable ({exc_brief(shape_err)})", flush=True)

                return template_data
            else:
                # Bug 4 case 1: JSON without a "cells" key — not a valid grid
                print(
                    f"[TEMPLATE] WARNING (Bug4): description is JSON but lacks 'cells' "
                    f"key — falling through to columns_json",
                    flush=True,
                )
        except json.JSONDecodeError:
            # Bug 4 case 2: plain text description — use it as unguided extraction context
            plain_text = tpl.description.strip() if tpl.description else ""
            if plain_text:
                print(
                    f"[TEMPLATE] WARNING (Bug4): description is plain text — "
                    f"routing to unguided extraction with context: {plain_text[:80]}",
                    flush=True,
                )
                return {
                    "mode": "layout",
                    "layout": {"cells": {}, "extractTargets": []},
                    "doc_type": tpl.document_type or "other",
                    "name": tpl.name,
                    "plain_text_description": plain_text,
                    "regions": {
                        "primary_mode": "unguided",
                        "explicit_targets": [],
                        "kv_pairs": [],
                        "two_col_pairs": [],
                        "table_regions": [],
                        "transposed_tables": [],
                        "section_label_rows": set(),
                        "has_explicit_targets": False,
                        "has_table": False,
                        "max_row": 0,
                        "max_col": 0,
                        "plain_text_description": plain_text,
                        "needs_section_context": False,
                    },
                }
        except Exception as e:
            import traceback
            print(f"[TEMPLATE] description parse error: {exc_brief(e)}", flush=True)
            print_safe_traceback()

    if not tpl.columns_json:
        return None

    try:
        raw = json.loads(tpl.columns_json)
        if isinstance(raw, dict) and "extractTargets" in raw:
            template_data = {
                "mode": "layout",
                "layout": raw,
                "doc_type": tpl.document_type or "other",
                "name": tpl.name,
            }
            template_data["regions"] = _analyse_template_regions(raw)
            return template_data

        header_cols = []
        for i, item in enumerate(raw if isinstance(raw, list) else []):
            if isinstance(item, str):
                col = {"name": item, "type": "Text", "order": i}
            else:
                col = {"name": item.get("name",""), "type": item.get("type","Text"),
                       "order": item.get("order", i)}
            header_cols.append(col)

        return {
            "mode": "columns",
            "header_cols": header_cols,
            "doc_type": tpl.document_type or "other",
            "name": tpl.name,
        }
    except Exception as e:
        print(f"[TEMPLATE] columns_json parse error: {exc_brief(e)}", flush=True)
        return None


def _analyse_template_regions(layout: dict) -> dict:
    """
    Analyse the template grid and identify ALL extraction regions.

    This replaces the binary TABLE/FORM decision with a rich structural map
    that tells the AI exactly what the user designed and where.

    Detects:
      - key_value_pairs: label in col N, empty extract cell in col N+1
      - two_column_form: labels+values on BOTH left and right halves
      - table_header: a row of column headers with no values below
      - free_positions: explicit Extract here cells at any grid position
      - blank_near_label: empty cells adjacent to labels (auto-fill mode)

    Returns a regions dict that gets passed to the AI prompt.
    """
    cells = layout.get("cells", {})
    extract_targets = layout.get("extractTargets", [])

    # Parse all cells into a row/col grid
    grid = {}  # (row, col) -> {value, extractTarget, style}
    max_row, max_col = 0, 0
    for key, cell in cells.items():
        if not isinstance(cell, dict):
            continue
        parts = key.split(",")
        if len(parts) != 2:
            continue
        try:
            r, c = int(parts[0]), int(parts[1])
        except (ValueError, TypeError):
            continue
        max_row = max(max_row, r)
        max_col = max(max_col, c)
        # Safely get values — all fields may be None in malformed templates
        raw_val  = cell.get("value")
        val_str  = str(raw_val).strip() if raw_val is not None else ""
        merge_span   = cell.get("mergeSpan")
        merge_parent = cell.get("mergeParent")
        grid[(r, c)] = {
            "value":         val_str,
            "extractTarget": bool(cell.get("extractTarget", False)),
            "mergeParent":   merge_parent if isinstance(merge_parent, (list, dict)) else None,
            "mergeSpan":     merge_span   if isinstance(merge_span,   dict)         else None,
            "ref":           _cell_ref(r, c),
            "row":           r,
            "col":           c,
        }

    # Find all explicit Extract here targets
    # EXCLUDE: merge child cells whose parent is a section header (merged label row)
    # e.g. "Vendor Info" merged across 4 cols — its child cells should not be targets
    merged_section_header_rows = set()
    for (r, c), cell in grid.items():
        if cell["mergeSpan"] and cell["value"] and not cell["extractTarget"]:
            # This is a merged label cell (section header) — mark its row
            span_cols = (cell["mergeSpan"] or {}).get("cols", 1)
            if span_cols >= 2:  # only wide merges are section headers
                merged_section_header_rows.add(r)

    explicit_targets = []
    for (r, c), cell in grid.items():
        if cell["extractTarget"] and not cell["value"]:
            # Skip merge child cells in section header rows
            if cell["mergeParent"] and r in merged_section_header_rows:
                continue
            # Skip cells whose own row is a merged section header
            if r in merged_section_header_rows:
                continue
            # Find the nearest label (left, above, or two left)
            label = ""
            for dc in range(1, 4):  # look up to 3 cells to the left
                neighbor = grid.get((r, c - dc))
                if neighbor and neighbor["value"]:
                    label = neighbor["value"]
                    break
            if not label:
                neighbor = grid.get((r - 1, c))
                if neighbor and neighbor["value"]:
                    label = neighbor["value"]
            explicit_targets.append({
                "ref": _cell_ref(r, c),
                "row": r, "col": c,
                "label": label or f"field at {_cell_ref(r, c)}",
            })

    # Also check extractTargets list from layout
    for t in extract_targets:
        ref = _cell_ref(t.get("r", 0), t.get("c", 0))
        if not any(e["ref"] == ref for e in explicit_targets):
            explicit_targets.append({
                "ref": ref,
                "row": t.get("r", 0),
                "col": t.get("c", 0),
                "label": t.get("label", f"field at {ref}"),
            })

    # Detect key-value pairs (label col N, empty col N+1, same row)
    # Section label rows (rows above table headers) are excluded below
    # after rows_with_content is built
    kv_pairs = []
    for (r, c), cell in grid.items():
        if cell["value"] and not cell["extractTarget"]:
            right = grid.get((r, c + 1))
            if right and (right["extractTarget"] or not right["value"]):
                kv_pairs.append({
                    "label": cell["value"],
                    "label_ref": cell["ref"],
                    "value_ref": _cell_ref(r, c + 1),
                    "row": r,
                })

    # Detect two-column form layout
    # Pattern: labels in col A, values in col B, AND labels in col C, values in col D
    # More generally: labels in even cols, values in odd cols (or vice versa)
    two_col_pairs = []
    for (r, c), cell in grid.items():
        if cell["value"] and not cell["extractTarget"]:
            # Look for a value cell 2 columns to the right (two-column layout)
            right2 = grid.get((r, c + 2))
            if right2 and (right2["extractTarget"] or not right2["value"]):
                # Check there is also a label at c+1 or c+2 area
                mid = grid.get((r, c + 1))
                if mid and mid["value"] and not mid["extractTarget"]:
                    # Pattern: LabelA | LabelB | ValueA | ValueB
                    far_right = grid.get((r, c + 3))
                    if far_right and (far_right["extractTarget"] or not far_right["value"]):
                        two_col_pairs.append({
                            "left_label": cell["value"],
                            "left_label_ref": cell["ref"],
                            "left_value_ref": _cell_ref(r, c + 2),
                            "right_label": mid["value"],
                            "right_label_ref": mid["ref"],
                            "right_value_ref": _cell_ref(r, c + 3),
                            "row": r,
                        })

    # Detect table headers — the actual column header row for repeating data rows.
    # Rules for a valid table header row:
    #   1. Has 2+ non-empty cells
    #   2. NONE of the cells in that row are extract targets (those are form fields)
    #   3. NONE of the cells in adjacent columns of same row are extract targets
    #   4. The row BELOW is empty (data will go there) OR it is the last content row
    # This prevents two-column form rows from being misidentified as table headers.
    table_regions = []
    rows_with_content = {}
    for (r, c), cell in grid.items():
        if cell["value"] or cell["extractTarget"]:
            rows_with_content.setdefault(r, []).append(c)

    # Build a set of rows that contain extract targets — these are form rows.
    # IMPORTANT: Only mark a row as a form row if IT ITSELF contains extract targets.
    form_rows_set = set()
    for (r, c), cell in grid.items():
        if cell["extractTarget"]:
            form_rows_set.add(r)

    # Now compute pre_table_header_rows — rows directly above table header candidates.
    # These are section labels (e.g. "Earning Table", "Deduction Table") and should
    # be excluded from kv_pairs so they aren't sent to AI as form fields to fill.
    pre_table_header_rows = set()
    for r_candidate, cols_candidate in rows_with_content.items():
        if r_candidate in form_rows_set:
            continue
        value_cols_candidate = [c for c in cols_candidate
                                if grid.get((r_candidate, c))
                                and grid[(r_candidate, c)]["value"]
                                and not grid[(r_candidate, c)]["extractTarget"]]
        if len(value_cols_candidate) >= 2:
            # Bug 2: look 2 rows below — a single row of example values is still
            # a valid table header. Only skip if BOTH r+1 AND r+2 have content.
            below1 = [c for c in rows_with_content.get(r_candidate + 1, [])
                      if grid.get((r_candidate + 1, c))
                      and grid[(r_candidate + 1, c)]["value"]
                      and not grid[(r_candidate + 1, c)]["extractTarget"]]
            below2 = [c for c in rows_with_content.get(r_candidate + 2, [])
                      if grid.get((r_candidate + 2, c))
                      and grid[(r_candidate + 2, c)]["value"]
                      and not grid[(r_candidate + 2, c)]["extractTarget"]]
            if below1 and below2:
                continue  # two consecutive content rows below → not a table header
            # This row is a real table header — mark rows above it as section labels
            for r_above in range(max(0, r_candidate - 4), r_candidate):
                if r_above not in form_rows_set:
                    pre_table_header_rows.add(r_above)

    # Save unfiltered kv_pairs for parallel-column group detection.
    # The filter below removes rows that are section labels above table headers
    # (e.g. "Total" rows at row 9 that sit above the liabilities header at row 10).
    # Those rows ARE valid kv_pairs for structural detection — if we filter them out
    # before parallel detection, the band item count drops below the ≥3 threshold
    # and the balance sheet parallel groups are never found.
    kv_pairs_for_parallel = kv_pairs[:]   # snapshot BEFORE section-label filter

    # Filter kv_pairs to exclude section label rows (for AI prompts / mode logic)
    kv_pairs = [kv for kv in kv_pairs if kv["row"] not in pre_table_header_rows]

    for r, cols in sorted(rows_with_content.items()):
        # Skip rows that are form rows (have extract targets nearby)
        if r in form_rows_set:
            continue

        value_cols = [c for c in cols
                      if grid.get((r, c)) and grid[(r, c)]["value"]
                      and not grid[(r, c)]["extractTarget"]]

        if len(value_cols) < 2:
            continue

        # A valid table header MUST NOT have two consecutive content rows below it.
        # Form section headers (like "Summary", "Opening Bal | Closing Bal")
        # have content below them — they are NOT table headers.
        # A table header with one example row below (Bug 2: client puts sample data)
        # is still a valid table header.
        # Bug 2: check r+1 AND r+2 — only skip when BOTH rows have content.
        below1_cols = [c for c in rows_with_content.get(r + 1, [])
                       if grid.get((r + 1, c)) and grid[(r + 1, c)]["value"]
                       and not grid[(r + 1, c)]["extractTarget"]]
        below2_cols = [c for c in rows_with_content.get(r + 2, [])
                       if grid.get((r + 2, c)) and grid[(r + 2, c)]["value"]
                       and not grid[(r + 2, c)]["extractTarget"]]

        # Two consecutive content rows below → this is a form section, not a table header
        if below1_cols and below2_cols:
            continue

        # Also skip if this row is a merged section header
        if r in merged_section_header_rows:
            continue

        row_labels = [grid[(r, c)]["value"] for c in sorted(value_cols)]

        min_col = min(value_cols)
        max_col = max(value_cols)
        table_regions.append({
            "header_row": r,
            "start_col": min_col,
            "end_col": max_col,
            "start_ref": _cell_ref(r, min_col),
            "end_ref": _cell_ref(r, max_col),
            "column_names": row_labels,
            "is_header_only": True,
        })

    # Keep ALL valid table regions — sorted by row then by column position
    # Each table gets a label from the nearest section header above it
    # OR from its column position if it shares a row with another table
    if table_regions:
        # Sort by row first, then by start column
        table_regions.sort(key=lambda t: (t["header_row"], t["start_col"]))

        # Group tables that share the same header_row
        same_row_groups = {}
        for tbl in table_regions:
            same_row_groups.setdefault(tbl["header_row"], []).append(tbl)

        for row, tbls_on_row in same_row_groups.items():
            for idx, tbl in enumerate(tbls_on_row):
                # Find section label: row directly above table header (1-2 rows max)
                # MUST be blank row between form fields and table OR be a merged header
                # Do NOT pick up form field labels that are 3+ rows above
                section_label = ""
                for row_above in range(row - 1, max(0, row - 3), -1):
                    for c in range(tbl["start_col"], tbl["end_col"] + 1):
                        cell = grid.get((row_above, c))
                        if not cell or not cell["value"] or cell["extractTarget"]:
                            continue
                        # Accept as section label only if:
                        # 1. It's a wide merged cell (span >= 2 cols), OR
                        # 2. It's directly above (1 row) and the row between is blank
                        merge_span = cell.get("mergeSpan") or {}
                        is_merged = merge_span.get("cols", 1) >= 2
                        is_directly_above = (row_above == row - 1)
                        row_between_empty = not any(
                            (grid.get((r, c2)) or {}).get("value") or
                            (grid.get((r, c2)) or {}).get("extractTarget")
                            for r in range(row_above + 1, row)
                            for c2 in range(tbl["start_col"], tbl["end_col"] + 1)
                        )
                        if is_merged or (is_directly_above and row_between_empty):
                            section_label = cell["value"]
                            break
                    if section_label:
                        break

                if not section_label:
                    if len(tbls_on_row) > 1:
                        # Multiple tables on same row — use column range as label
                        start_letter = chr(ord('A') + tbl["start_col"])
                        end_letter   = chr(ord('A') + tbl["end_col"])
                        section_label = (
                            f"Table {_cell_ref(row, tbl['start_col'])[:1]}"
                            f"-{_cell_ref(row, tbl['end_col'])[:1]}"
                            f" ({', '.join(tbl['column_names'][:2])})"
                        )
                    else:
                        section_label = f"Table {table_regions.index(tbl) + 1}"

                tbl["section_label"] = section_label

                # Store col_range so AI knows which columns belong to this table
                tbl["col_range"] = (tbl["start_col"], tbl["end_col"])
                tbl["col_letters"] = (
                    chr(ord('A') + tbl["start_col"]),
                    chr(ord('A') + min(tbl["end_col"], 25))
                )

    print(f"[REGION] {len(table_regions)} table(s) detected: "
          f"{[t.get('section_label','?') for t in table_regions]}", flush=True)

    # Detect transposed tables (headers in col A, data in cols B+)
    transposed_tables = _detect_transposed_table(grid, max_row, max_col)
    if transposed_tables:
        print(f"[REGION] {len(transposed_tables)} transposed table(s) detected", flush=True)

    # Build section_label_rows — rows that:
    #   1. Have text content
    #   2. No extract targets on the row
    #   3. Are NOT table header rows themselves
    #   4. Are directly above a table header row (within 4 rows)
    # These rows are template structure labels, not data — never write as data rows.
    table_header_row_set = {t["header_row"] for t in table_regions}
    section_label_rows = set()
    for tbl in table_regions:
        hr = tbl["header_row"]
        # Only look 2 rows above the table header for section labels.
        # Looking further up risks capturing form section headers (like "Summary")
        # that belong to the form fields above, not to this table.
        for r_above in range(max(0, hr - 2), hr):
            if r_above in table_header_row_set:
                continue
            if r_above in form_rows_set:
                continue
            row_has_text = any(
                grid.get((r_above, c), {}).get("value", "")
                for c in range(max_col + 1)
            )
            if row_has_text:
                section_label_rows.add(r_above)

    # Build summary for AI
    has_explicit_targets = len(explicit_targets) > 0
    has_kv_pairs = len(kv_pairs) > 0
    has_two_col = len(two_col_pairs) > 0
    has_table = len(table_regions) > 0

    # Mixed mode: has BOTH form fields (targets or kv pairs) AND a table
    # This is the most important detection — Balance Sheet, Expense Report,
    # Purchase Order, Tax Form all have header fields + line items table
    if has_table and (has_explicit_targets or has_kv_pairs):
        primary_mode = "mixed"
    elif not has_table and has_explicit_targets:
        primary_mode = "form_with_targets"
    elif not has_table and has_kv_pairs:
        primary_mode = "form_kv"
    elif has_table and not has_explicit_targets and not has_kv_pairs:
        primary_mode = "table"
    elif has_two_col:
        # Two-column form detected but no explicit targets or kv_pairs
        primary_mode = "form_kv"
    else:
        # Bug 1: all region lists empty — fall back to unguided extraction
        # using only the doc_type system prompt
        primary_mode = "unguided"
        print(
            "[TEMPLATE] WARNING (Bug1): no regions detected in template grid "
            "— switching to unguided extraction (doc_type system prompt only)",
            flush=True,
        )

    print(f"[REGION] mode={primary_mode} targets={len(explicit_targets)} "
          f"kv={len(kv_pairs)} two_col={len(two_col_pairs)} "
          f"tables={len(table_regions)} grid={max_row+1}x{max_col+1}", flush=True)

    # ── PARALLEL COLUMN GROUPS DETECTION ──────────────────────────────────────────
    # Detect when template has two or more side-by-side label/value column bands
    # (e.g. balance sheet: Current Assets in A-B, Non-Current Assets in C-D).
    # When parallel groups ARE detected, ALWAYS override mode to parallel_groups.
    # The "table regions" on balance-sheet templates are the parallel group section
    # headers (e.g. row 0: "Current assets | Amount | Non-current assets | Amount"),
    # not real repeating-row tables. Using parallel_groups routes to _write_form_excel
    # which iterates every template row including dynamic fill rows.
    # Use the unfiltered snapshot so Total/header rows (which may have been
    # excluded from kv_pairs by the section-label filter above) still contribute
    # to band item counts — preventing false-negative parallel group detection.
    parallel_column_groups = _detect_parallel_column_groups(
        kv_pairs_for_parallel, grid, max_row, max_col
    )
    if parallel_column_groups:
        primary_mode = "parallel_groups"
        # FIX 1: when parallel groups are active, suppress all other region
        # interpretations so ONLY parallel-group instructions reach the AI.
        # Leaving these populated makes the prompt contradictory (telling Gemini
        # to fill cells AND extract tables AND transpose the same grid).
        table_regions = []
        transposed_tables = []
        two_col_pairs = []
        has_table = False

    return {
        "primary_mode":            primary_mode,
        "explicit_targets":        explicit_targets,
        "kv_pairs":                kv_pairs,
        "two_col_pairs":           two_col_pairs,
        "table_regions":           table_regions,
        "transposed_tables":       transposed_tables,
        "section_label_rows":      section_label_rows,
        "parallel_column_groups":  parallel_column_groups,
        "grid_size":               {"rows": max_row + 1, "cols": max_col + 1},
        "has_explicit_targets":    has_explicit_targets,
        "has_table":               has_table,
        "max_row":                 max_row,
        "max_col":                 max_col,
    }


def _detect_parallel_column_groups(kv_pairs: list, grid: dict,
                                    max_row: int, max_col: int) -> list:
    """
    Detect parallel column groups: two or more independent label/value column bands
    that occupy the same row range in the template.

    Example balance sheet layout (rows 0-N):
      col A = Current assets labels  | col B = empty (extract) |
      col C = Non-current labels     | col D = empty (extract)

    Returns [] when not detected, or a list of group dicts:
      [{group_id, label_col, value_col, label_col_letter, value_col_letter,
        section_label, items:[{label, label_ref, value_ref, row}]}]
    """
    if len(kv_pairs) < 4:
        return []

    # Group kv_pairs by their label column index
    col_groups: dict = {}
    for kv in kv_pairs:
        label_ref = kv.get("label_ref", "")
        if not label_ref:
            continue
        col_letters = "".join(ch for ch in label_ref if ch.isalpha()).upper()
        if not col_letters:
            continue
        col_idx = sum(
            (ord(ch) - 64) * (26 ** i)
            for i, ch in enumerate(reversed(col_letters))
        ) - 1
        col_groups.setdefault(col_idx, []).append(kv)

    # Need 2+ bands with at least 3 items each
    bands = sorted(
        [(col, kvs) for col, kvs in col_groups.items() if len(kvs) >= 3],
        key=lambda x: x[0],
    )
    if len(bands) < 2:
        return []

    # Verify that bands share significant row overlap (>= 40% of their union)
    band_row_sets = [set(kv["row"] for kv in kvs) for _, kvs in bands]
    has_overlap = False
    for i in range(len(band_row_sets)):
        for j in range(i + 1, len(band_row_sets)):
            union = band_row_sets[i] | band_row_sets[j]
            intersect = band_row_sets[i] & band_row_sets[j]
            if union and len(intersect) / len(union) >= 0.40:
                has_overlap = True
                break
        if has_overlap:
            break

    if not has_overlap:
        return []

    parallel_groups = []
    for i, (label_col, items) in enumerate(bands):
        value_col = label_col + 1
        l_letter = chr(ord('A') + min(label_col, 25))
        v_letter = chr(ord('A') + min(value_col, 25))

        # Section label: the last non-item row at-or-above the first item row
        # at this column (i.e. the heading row that names the group).
        item_rows = {kv["row"] for kv in items}
        first_item_row = min(item_rows)
        section_label = ""
        for r in range(0, first_item_row + 1):
            if r in item_rows:
                continue
            cell = grid.get((r, label_col))
            if cell and cell["value"] and not cell["extractTarget"]:
                section_label = cell["value"]  # keep updating — take last found

        if not section_label:
            section_label = f"Group {i + 1} (columns {l_letter}-{v_letter})"

        parallel_groups.append({
            "group_id":         i + 1,
            "label_col":        label_col,
            "value_col":        value_col,
            "label_col_letter": l_letter,
            "value_col_letter": v_letter,
            "section_label":    section_label,
            "items":            sorted(items, key=lambda x: x["row"]),
        })

    print(
        "[REGION] parallel_column_groups detected: "
        + ", ".join(
            f'"{g["section_label"]}" ({g["label_col_letter"]}-{g["value_col_letter"]})'
            for g in parallel_groups
        ),
        flush=True,
    )
    return parallel_groups


def _load_registry():
    if not hasattr(_load_registry, "_cache"):
        try:
            import importlib.util
            reg_file = Path(__file__).resolve().parent / "prompt_registry.py"
            if reg_file.exists():
                spec = importlib.util.spec_from_file_location("prompt_registry", reg_file)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                _load_registry._cache = mod
                print(f"[REGISTRY] Loaded from {reg_file}", flush=True)
            else:
                _load_registry._cache = None
        except Exception as e:
            print(f"[REGISTRY] Load error: {exc_brief(e)}", flush=True)
            _load_registry._cache = None
    return _load_registry._cache


def _get_system_prompt(doc_type): r=_load_registry(); return r.get_system_prompt(doc_type) if r else f"You are an expert {doc_type} extraction specialist."


def _get_unguided_prompt(): r=_load_registry(); return r.get_unguided_prompt() if r else "You are an expert document data extraction AI. Extract all visible fields as JSON."


def _get_table_rules(doc_type): r=_load_registry(); return (r.get_table_rules(doc_type) or "") if r else ""


def _get_numeric_fields(doc_type): r=_load_registry(); return r.get_numeric_fields(doc_type) if r else []


def _classify_by_hints(text): r=_load_registry(); return r.classify_by_hints(text) if r else None


_FINANCIAL_SECTIONED_TYPES = frozenset({
    "balance_sheet", "income_statement", "audit_report", "payslip",
})


_GENERIC_FINANCIAL_COL_WORDS = frozenset({
    "total", "amount", "value", "balance", "net", "gross", "subtotal",
    "debit", "credit", "description",
})


def _detect_section_context_risk(regions: dict, doc_type: str) -> bool:
    """
    Return True when the template has generic repeated column headers (e.g. Total,
    Amount, Value) in a financial document type that contains section-level totals.
    These templates create ambiguity: the AI may pick the wrong section's total
    without explicit positional guidance.
    """
    if doc_type not in _FINANCIAL_SECTIONED_TYPES:
        return False
    table_regions = regions.get("table_regions", [])
    kv_pairs = regions.get("kv_pairs", [])
    explicit_targets = regions.get("explicit_targets", [])

    # Collect all column names from tables
    all_col_names_lower = [
        cn.lower().strip()
        for tr in table_regions
        for cn in tr.get("column_names", [])
    ]
    # Count how many generic financial words appear in column names
    generic_col_count = sum(
        1 for cn in all_col_names_lower
        if any(g in cn for g in _GENERIC_FINANCIAL_COL_WORDS)
    )
    # Also flag if kv_pairs or targets have multiple generic labels
    generic_field_count = sum(
        1 for kv in kv_pairs
        if any(g in kv.get("label", "").lower() for g in _GENERIC_FINANCIAL_COL_WORDS)
    ) + sum(
        1 for t in explicit_targets
        if any(g in t.get("label", "").lower() for g in _GENERIC_FINANCIAL_COL_WORDS)
    )

    risk = generic_col_count >= 2 or generic_field_count >= 3
    if risk:
        print(
            f"[BUG5] Section-context risk detected: doc_type={doc_type} "
            f"generic_cols={generic_col_count} generic_fields={generic_field_count}",
            flush=True,
        )
    return risk


def _cell_ref(r: int, c: int) -> str:
    col_letter = ""
    n = c
    while True:
        col_letter = chr(65 + (n % 26)) + col_letter
        n = n // 26 - 1
        if n < 0:
            break
    return f"{col_letter}{r + 1}"


def _col_letter(c: int) -> str:
    letter = ""
    n = c
    while True:
        letter = chr(65 + (n % 26)) + letter
        n = n // 26 - 1
        if n < 0:
            break
    return letter


def _detect_transposed_table(grid: dict, max_row: int, max_col: int) -> list:
    """
    Detect transposed (horizontal) tables where:
    - Headers are in COLUMN A (rows going down)
    - Data is in columns B, C, D... (each column = one record)

    Example:
      A1=Name    B1=Alice  C1=Bob
      A2=Dept    B2=HR     C2=Eng
      A3=Salary  B3=50000  C3=60000

    Returns list of transposed table regions, each with:
      header_col, start_row, end_row, row_names, data_cols
    """
    transposed = []

    # Check if column 0 has multiple consecutive labels
    col0_labels = []
    for r in range(max_row + 1):
        cell = grid.get((r, 0))
        if cell and cell["value"] and not cell["extractTarget"]:
            col0_labels.append((r, cell["value"]))

    if len(col0_labels) < 3:
        return []  # Not enough labels in col A to be a transposed table

    # Check if columns 1+ have data in the same rows
    label_rows = [r for r, _ in col0_labels]
    data_cols  = []
    for c in range(1, min(max_col + 1, 20)):
        filled = sum(
            1 for r in label_rows
            if grid.get((r, c)) and grid[(r, c)]["value"]
        )
        if filled >= len(label_rows) * 0.5:  # at least 50% of label rows have data
            data_cols.append(c)

    if data_cols:
        transposed.append({
            "header_col":  0,
            "start_row":   min(label_rows),
            "end_row":     max(label_rows),
            "row_names":   [lbl for _, lbl in col0_labels],
            "data_cols":   data_cols,
            "is_transposed": True,
        })

    return transposed
