"""The legacy Excel writers (layout, table, form, mixed, flat) for old jobs and the image path.

Moved verbatim from app/api/routes/extract.py (round 13); extract.py re-exports every name.
"""

import app.services.paths  # noqa: F401  (engine on sys.path)
from typing import Optional
from app.services.excel_cells import _apply_cell_style
from app.services.excel_cells import _calculate_layout
from app.services.template_parsing import _col_letter
from app.services.excel_cells import _find_template_dimensions
from app.services.excel_cells import _marks_or_off
from app.services.excel_cells import _review_status_unknown
import re
# --imports-end--


def _write_layout_excel(ws, doc_results, sheet_data, cells_tpl, openpyxl_mod,
                        marks=None):
    """
    Layout-aware writer with dynamic row expansion + push-down. For each document it
    plans positions via _calculate_layout (sections derived from binding_column_groups
    + the extracted row counts), expands any section that has more line items than the
    template provides, pushes all content below down, and stacks multiple documents
    with a 2-row gap. Falls back to legacy fixed-position writing when no column
    groups are available.
    """
    from openpyxl.utils.cell import column_index_from_string, coordinate_from_string
    sm = _marks_or_off(ws, marks)
    ed = {}                   # the current block's result; set in the loop

    def _row_mark(cell, row, value):
        sm.row_cell(cell, ed, {"value": value,
                               "_confidence": (row or {}).get("confidence")}, "value")

    def _set_num(cell, raw):
        # STEP 7 — normalize: strip currency symbols + thousands separators, convert
        # accounting negatives (500) -> -500; numeric -> float/int, else keep text.
        s = str(raw).strip()
        for sym in ("$", "£", "€", "₹", "¥", ","):
            s = s.replace(sym, "")
        s = s.strip()
        if s.startswith("(") and s.endswith(")"):
            s = "-" + s[1:-1].strip()
        try:
            if s and re.match(r'^-?[0-9]+\.?[0-9]*$', s):
                cell.value = float(s) if "." in s else int(s)
                return
        except (ValueError, TypeError):
            pass
        cell.value = str(raw)

    def _nrm(s):
        return re.sub(r'[^a-z0-9]+', '', str(s or "").lower())

    def _col_idx(letter):
        try:
            return column_index_from_string(str(letter).upper())
        except Exception:
            return None

    # A1 — semantic section↔group matching. Canonicalizes common accounting
    # phrasing (long-term ↔ non-current, stockholders ↔ shareholders, ...) then
    # scores label token sets by Jaccard similarity. Generic — no document names.
    _SEM_CANON = (
        ("long term", "noncurrent"), ("long-term", "noncurrent"),
        ("longterm", "noncurrent"), ("non current", "noncurrent"),
        ("non-current", "noncurrent"), ("noncurrent", "noncurrent"),
        ("fixed asset", "noncurrent asset"),
        ("short term", "current"), ("short-term", "current"),
        ("stockholder", "shareholder"), ("owner", "shareholder"),
    )
    _SEM_STOP = {"total", "and", "the", "of", "amount", "amounts", "section"}

    def _sem_tokens(label):
        s = re.sub(r"[^a-z0-9]+", " ", str(label or "").lower()).strip()
        for a, b in _SEM_CANON:
            s = s.replace(a, b)
        toks = set()
        for t in s.split():
            if not t or t in _SEM_STOP:
                continue
            toks.add(t[:-1] if t.endswith("s") else t)   # crude plural fold
        return toks

    def _sem_score(a, b):
        ta, tb = _sem_tokens(a), _sem_tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    # A6 — bounding box from CONTENT cells only (value / extractTarget / merge),
    # so stray styled-but-empty cells can't stretch the output area.
    max_tr, max_tc_content = 0, 0
    for k, cd in cells_tpl.items():
        if not isinstance(cd, dict) or "," not in k:
            continue
        try:
            _r, _c = int(k.split(",")[0]), int(k.split(",")[1])
        except ValueError:
            continue
        if (str(cd.get("value") or "").strip() or cd.get("extractTarget")
                or cd.get("mergeSpan") or cd.get("mergeParent")):
            max_tr = max(max_tr, _r)
            max_tc_content = max(max_tc_content, _c)

    doc_offset = 0          # accumulates across document blocks (with gap rows)
    GAP_BETWEEN_DOCS = 2

    for block_idx, doc in enumerate(doc_results):
        ed = doc.get_extracted_data() or {}
        ls = ed.get("layout_sections", {}) if isinstance(ed, dict) else {}
        groups = ed.get("binding_column_groups", []) if isinstance(ed, dict) else []
        if block_idx > 0:
            doc_offset += GAP_BETWEEN_DOCS

        # ── STEP 1+2: dedup duplicate extracted sections, then match each
        #    extracted section to a template group (exact -> fuzzy/subset). A group
        #    may collect MORE THAN ONE matched section (concatenated in order). ──
        raw_secs = [(k, (v.get("rows", []) or [])) for k, v in
                    (ls.items() if isinstance(ls, dict) else []) if isinstance(v, dict)]

        # ── A2: drop sections whose row CONTENT is identical to one already kept
        #    (same labels + values in the same order) — the source of the
        #    "Long-term Liabilities written twice" duplication. ──
        def _content_sig(rows):
            return tuple((_nrm(r.get("label")), _nrm(str(r.get("value"))))
                         for r in rows if isinstance(r, dict)
                         and (r.get("label") or r.get("value") not in (None, "")))

        _seen_sigs, _deduped = {}, []
        for k, r in raw_secs:
            sig = _content_sig(r)
            if sig and sig in _seen_sigs:
                print(f"[EXPORT] layout: dropped section '{k}' — identical content "
                      f"to '{_seen_sigs[sig]}'", flush=True)
                continue
            if sig:
                _seen_sigs[sig] = k
            _deduped.append((k, r))
        raw_secs = _deduped

        def _labset(rows):
            return {_nrm(r.get("label")) for r in rows
                    if isinstance(r, dict) and r.get("label")}

        def _match_group(sec_key):
            nk = _nrm(sec_key)
            for g in groups:                                  # 1. exact
                if _nrm(g.get("section_label")) == nk:
                    return g
            for g in groups:                                  # 2. fuzzy / subset
                gn = _nrm(g.get("section_label"))
                if gn and (gn in nk or nk in gn):
                    return g
            # 3. A1: semantic (synonym-canonical token overlap) — catches e.g.
            #    document heading "Long-term Liabilities" vs template group
            #    "Non current liabilities", which no substring test can match.
            best, best_score = None, 0.0
            for g in groups:
                sc = _sem_score(sec_key, g.get("section_label"))
                if sc > best_score:
                    best, best_score = g, sc
            if best is not None and best_score >= 0.6:
                print(f"[EXPORT] layout: semantic match '{sec_key}' -> group "
                      f"'{best.get('section_label')}' (score {best_score:.2f}, "
                      f"cols {best.get('label_col_letter')}/"
                      f"{best.get('value_col_letter')})", flush=True)
                return best
            return None

        # ── Dedup — TIGHTENED. Only drop a section k1 when it is a redundant
        #    superset of a section k2 that is ALREADY captured by a column group,
        #    AND k1 adds nothing beyond k2 except (at most) one subtotal label.
        #    This drops pure "<Group> + subtotal" duplicates (e.g. "Total Current
        #    Assets" duplicating the "Current assets" group) while KEEPING
        #    multi-section roll-ups and unique summaries (TOTAL ASSETS, TOTAL
        #    LIABILITIES, Shareholders Equity, Long-term Liabilities, ...). A section
        #    is NEVER dropped just for sharing a few labels with another.
        drop = set()
        for i, (k1, r1) in enumerate(raw_secs):
            for j, (k2, r2) in enumerate(raw_secs):
                if i == j or k1 in drop or k2 in drop:
                    continue
                l1, l2 = _labset(r1), _labset(r2)
                if not l1 or not l2:
                    continue
                inter = len(l1 & l2)
                if (inter / len(l2) >= 0.9              # 90%+ of k2's labels are in k1
                        and len(r1) > len(r2)           # k1 has MORE rows than k2
                        and _match_group(k2) is not None  # k2 is already in a column group
                        and len(l1 - l2) <= 1):         # k1 adds <=1 label (its subtotal)
                    drop.add(k1)        # k1 is the redundant superset -> drop it
        if drop:
            print(f"[EXPORT] layout: dropped duplicate section(s) {sorted(drop)}", flush=True)
        kept = [(k, r) for k, r in raw_secs if k not in drop]

        matched_to, used = {}, set()
        for k, r in kept:
            g = _match_group(k)
            if g is not None:
                matched_to.setdefault(g["group_id"], []).extend(r)
                used.add(k)
        unmatched = [(k, r) for k, r in kept if k not in used]

        # ── S4: place still-unmatched sections into an EMPTY column group whose
        #    PARALLEL PARTNER already has content (the C/D half of a band whose
        #    A/B half matched). Candidates are ranked by semantic score against
        #    the section label; ties fall back to template order. Only truly
        #    orphaned sections remain for the A/B overflow area. ──
        if unmatched and groups:
            remaining = []
            for k, r in unmatched:
                cands = []
                for g in groups:
                    pid = g.get("parallel_group_id")
                    if pid is None or g["group_id"] in matched_to:
                        continue
                    partner_filled = any(
                        g2["group_id"] in matched_to
                        and g2.get("parallel_group_id") == pid
                        and g2["group_id"] != g["group_id"]
                        for g2 in groups)
                    if partner_filled:
                        cands.append(g)
                if cands:
                    best = max(cands, key=lambda g: _sem_score(k, g.get("section_label")))
                    print(f"[EXPORT] layout: S4 overflow section '{k}' -> parallel "
                          f"group '{best.get('section_label')}' (cols "
                          f"{best.get('label_col_letter')}/{best.get('value_col_letter')}, "
                          f"parallel_group_id={best.get('parallel_group_id')}, "
                          f"sem={_sem_score(k, best.get('section_label')):.2f})", flush=True)
                    matched_to.setdefault(best["group_id"], []).extend(r)
                else:
                    remaining.append((k, r))
            unmatched = remaining

        sections = []
        for g in groups:
            rows = matched_to.get(g["group_id"], [])
            sections.append({
                "section_label":      g.get("section_label", ""),
                "header_row":         max(0, int(g.get("start_row", 0)) - 1),
                "template_start_row": int(g.get("start_row", 0)),
                "template_end_row":   int(g.get("end_row", 0)),
                "total_row":          g.get("total_row"),
                "extracted_rows":     len(rows),
                "label_col_letter":   (g.get("label_col_letter") or "").upper(),
                "value_col_letter":   (g.get("value_col_letter") or "").upper(),
                "_rows":              rows,
            })

        plan = _calculate_layout(sections)

        # ── Row-shift map: a template row shifts by the overflow of every band whose
        #    data ends above it, plus the A4 gap row of every band whose CONTENT
        #    (data + totals) ends above it. ──
        band_shifts = sorted({(p["template_end_row"], p["overflow"]) for p in plan}
                             | {(p["content_end_row"], p["gap"]) for p in plan})

        def out_row(tr0):
            shift = sum(o for (e, o) in band_shifts if e < tr0)
            return tr0 + shift + doc_offset

        # ── 1. Static template cells at their shifted positions ──
        for key, cell_def in cells_tpl.items():
            if not isinstance(cell_def, dict):
                continue
            parts = key.split(",")
            if len(parts) != 2:
                continue
            try:
                tr, tc = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            # A6 — never touch cells outside the template's content bounding box
            if tr > max_tr or tc > max_tc_content:
                continue
            v = str(cell_def.get("value") or "").strip()
            if not v and not cell_def.get("style"):
                continue
            xl = ws.cell(row=out_row(tr) + 1, column=tc + 1)
            if v:
                xl.value = v
            if cell_def.get("style"):
                _apply_cell_style(xl, cell_def["style"], openpyxl_mod)

        # ── 2. Section line items, placed sequentially in the (expanded) band, using
        #       the GROUP's columns (this also corrects any wrong AI column). ──
        if plan:
            for p, sec in zip(plan, sections):
                lci = _col_idx(p["label_col_letter"])
                vci = _col_idx(p["value_col_letter"])
                for i, row in enumerate(sec["_rows"]):
                    if not isinstance(row, dict):
                        continue
                    out_r = p["data_start_actual"] + i + doc_offset + 1   # 1-based
                    lbl, vval = row.get("label"), row.get("value")
                    if lci and lbl not in (None, ""):
                        ws.cell(row=out_r, column=lci).value = str(lbl)
                    if vci and vval not in (None, ""):
                        _set_num(ws.cell(row=out_r, column=vci), vval)
                        _row_mark(ws.cell(row=out_r, column=vci), row, vval)
            if any(p["overflow"] for p in plan):
                _ov = sorted({(p["template_end_row"], p["overflow"]) for p in plan})
                print(f"[EXPORT] layout: doc {block_idx+1} expanded — "
                      f"overflow per band (template_end_row, rows) {_ov}", flush=True)
        else:
            # ── Legacy fallback: no column groups — write at the AI's row numbers ──
            for sec in (ls.values() if isinstance(ls, dict) else []):
                if not isinstance(sec, dict):
                    continue
                for row in sec.get("rows", []) or []:
                    if not isinstance(row, dict):
                        continue
                    try:
                        rnum = int(row.get("row"))
                    except (TypeError, ValueError):
                        continue
                    lci = _col_idx(row.get("label_col"))
                    vci = _col_idx(row.get("value_col"))
                    if lci and row.get("label") not in (None, ""):
                        ws.cell(row=rnum + doc_offset, column=lci).value = str(row.get("label"))
                    if vci and row.get("value") not in (None, ""):
                        _set_num(ws.cell(row=rnum + doc_offset, column=vci), row.get("value"))
                        _row_mark(ws.cell(row=rnum + doc_offset, column=vci), row,
                                  row.get("value"))

        # ── 3. Fixed cells (totals) by reference, row-shifted ──
        for ref, v in (ed.get("extracted_fields", {}) or {}).items():
            value = v.get("value", "") if isinstance(v, dict) else v
            if value in (None, ""):
                continue
            try:
                col_letter, rownum = coordinate_from_string(str(ref))
            except Exception:
                continue
            ci = _col_idx(col_letter)
            if not ci:
                continue
            # S2 — NEVER overwrite a static template cell (section header, column
            # header, label, merged child). A static cell = template text that is
            # not an extract target; a value_target's cell is empty in the template.
            tpl_cell = cells_tpl.get(f"{rownum - 1},{ci - 1}")
            if isinstance(tpl_cell, dict) and (
                    tpl_cell.get("mergeParent")
                    or (str(tpl_cell.get("value") or "").strip()
                        and not tpl_cell.get("extractTarget"))):
                print(f"[EXPORT] layout: SKIP extracted_fields {ref} -> static "
                      f"template cell ('{str(tpl_cell.get('value') or '')[:30]}') "
                      f"— never overwritten", flush=True)
                continue
            _set_num(ws.cell(row=out_row(rownum - 1) + 1, column=ci), value)
            sm.field(ws.cell(row=out_row(rownum - 1) + 1, column=ci), ed,
                     ref=str(ref), value=value)

        # ── STEP 4: write any unmatched extracted sections (NO DATA DROPPED) in the
        #    A/B columns after the template block, separated by gap rows. ──
        total_overflow = sum(o for (_e, o) in set(band_shifts)) if plan else 0
        consumed = (max_tr + 1) + total_overflow
        if unmatched:
            n_un = sum(len(r) for _k, r in unmatched)
            print(f"[EXPORT] layout: {n_un} unmatched row(s) in {len(unmatched)} "
                  f"section(s) -> A/B overflow", flush=True)
            cur = doc_offset + consumed + 1            # 0-based; one gap row before
            for _k, rows in unmatched:
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    lbl, vval = row.get("label"), row.get("value")
                    if lbl not in (None, ""):
                        ws.cell(row=cur + 1, column=1).value = str(lbl)
                    if vval not in (None, ""):
                        _set_num(ws.cell(row=cur + 1, column=2), vval)
                        _row_mark(ws.cell(row=cur + 1, column=2), row, vval)
                    cur += 1
                cur += 1                               # gap between overflow sections
            consumed = cur - doc_offset
        doc_offset += consumed

    print(f"[EXPORT] layout: wrote {len(doc_results)} document block(s)", flush=True)


def _write_table_excel(ws, doc_results, sheet_data, cells_tpl, template_regions, openpyxl_mod,
                       marks=None):
    """
    Table mode: write header row with original styles, then one data row per line item.
    Handles tables at any position in the grid (not just row 0).
    """
    from openpyxl.cell import MergedCell
    sm = _marks_or_off(ws, marks)
    table_regions = (template_regions or {}).get("table_regions", [])
    header_row_idx = table_regions[0]["header_row"] if table_regions else 0
    start_col_idx = table_regions[0]["start_col"] if table_regions else 0

    # Write ALL cells from the template (including any form fields above the table)
    _bx_r, _bx_c = _find_template_dimensions(cells_tpl)
    for key, cell_def in cells_tpl.items():
        if not isinstance(cell_def, dict): continue
        parts = key.split(",")
        if len(parts) != 2: continue
        tr, tc = int(parts[0]), int(parts[1])
        # A6 — skip cells outside the content bounding box
        if tr > _bx_r or tc > _bx_c:
            continue
        tpl_value = str(cell_def.get("value") or "").strip()
        if not tpl_value and not cell_def.get("style"):
            continue
        xl_cell = ws.cell(row=tr + 1, column=tc + 1)
        # Skip merged-cell children — read-only in openpyxl
        if isinstance(xl_cell, MergedCell):
            continue
        if tpl_value:
            xl_cell.value = tpl_value
        if cell_def.get("style"):
            _apply_cell_style(xl_cell, cell_def["style"], openpyxl_mod)

    # Write data rows starting from the row after the header
    col_names = []
    for tr in table_regions:
        col_names.extend(tr.get("column_names", []))
    col_names = list(dict.fromkeys(col_names))
    col_indices = {name: (start_col_idx + i) for i, name in enumerate(col_names)}

    current_row = header_row_idx + 2  # +1 for 1-based, +1 to skip header

    for doc_result in doc_results:
        extracted = doc_result.get_extracted_data()
        table_rows = extracted.get("table_rows", [])

        for row_data in table_rows:
            for col_name, c_idx in col_indices.items():
                val = row_data.get(col_name, "")
                if isinstance(val, dict):
                    val = val.get("value", "")
                xl_cell = ws.cell(row=current_row, column=c_idx + 1)
                if isinstance(xl_cell, MergedCell):
                    continue
                try:
                    xl_cell.value = (float(val) if "." in str(val) else int(val)) if val else val
                except (ValueError, TypeError):
                    xl_cell.value = val
                sm.row_cell(xl_cell, extracted, row_data, col_name)
            current_row += 1

    print(f"[EXPORT] table: header at row {header_row_idx+1}, "
          f"{current_row - header_row_idx - 2} data rows", flush=True)


def _write_form_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c, openpyxl_mod,
                      marks=None):
    """
    Form mode: one filled template block per document result.
    Multi-doc: 3 blank rows + grey divider between documents.
    """
    from openpyxl.styles import Font, PatternFill
    from openpyxl.cell import MergedCell
    merges_tpl   = sheet_data.get("merges", {})
    # Extra rows per block for separator (only applied from block 2 onwards)
    SEPARATOR_HEIGHT = 5  # 3 blank + 1 divider + 1 blank
    block_height = max_r + 2

    def get_row_offset(block_idx):
        """Calculate row offset for a block, accounting for separators."""
        if block_idx == 0:
            return 0
        return block_idx * block_height + block_idx * SEPARATOR_HEIGHT

    sm = _marks_or_off(ws, marks)
    for block_idx, doc_result in enumerate(doc_results):
        row_offset = get_row_offset(block_idx)
        extracted_data   = doc_result.get_extracted_data()
        extracted_fields = extracted_data.get("extracted_fields", {})
        validation       = extracted_data.get("validation", {})
        confidence_map   = validation.get("confidence_map", {})

        label_to_value = {
            k: (v.get("value","") if isinstance(v,dict) else str(v or ""))
            for k, v in extracted_data.get("extracted_data", {}).items()
            if not k.startswith("_label_")
        }

        # First pass: write all cells and collect numeric values by ref
        # so we can calculate formulas
        cell_values = {}  # ref -> numeric value for formula calculation

        for key, cell_def in cells_tpl.items():
            if not isinstance(cell_def, dict) or cell_def.get("mergeParent"):
                continue
            parts = key.split(",")
            if len(parts) != 2:
                continue
            tr, tc = int(parts[0]), int(parts[1])
            # A6 — never touch cells outside the template's content bounding box
            # (style-only / cleared editor cells would otherwise materialize as
            # empty columns in the output).
            if tr > max_r or tc > max_c:
                continue
            xl_cell = ws.cell(row=row_offset + tr + 1, column=tc + 1)
            # Skip merged-cell children — their .value/.style are read-only in openpyxl
            if isinstance(xl_cell, MergedCell):
                continue
            tpl_value = cell_def.get("value","").strip()

            ref = f"{_col_letter(tc)}{tr+1}"
            if cell_def.get("extractTarget"):
                filled = extracted_fields.get(ref) or label_to_value.get(tpl_value, "")
                if isinstance(filled, dict):
                    filled = filled.get("value", "")
                filled = filled if filled is not None else ""

                # Try to store as number for formula calculation
                try:
                    num_val = float(filled.replace(",","")) if filled else None
                    if num_val is not None:
                        xl_cell.value = num_val
                        cell_values[ref] = num_val
                    else:
                        xl_cell.value = filled
                except (ValueError, AttributeError):
                    xl_cell.value = filled
                # The review mark (it replaces the old low-confidence tint).
                if extracted_fields.get(ref):
                    sm.field(xl_cell, extracted_data, ref=ref, value=filled)
                else:
                    sm.field(xl_cell, extracted_data, label=tpl_value, value=filled)

            elif not tpl_value and ref in extracted_fields:
                # kv_pair value cell: empty in template but AI extracted a value
                kv_filled = extracted_fields.get(ref)
                if isinstance(kv_filled, dict):
                    kv_filled = kv_filled.get("value", "")
                kv_filled = kv_filled or ""
                try:
                    num_val = float(str(kv_filled).replace(",", "")) if kv_filled else None
                    xl_cell.value = num_val if num_val is not None else kv_filled
                    if num_val is not None:
                        cell_values[ref] = num_val
                except (ValueError, AttributeError):
                    xl_cell.value = kv_filled
                sm.field(xl_cell, extracted_data, ref=ref, value=kv_filled)

            elif tpl_value.startswith("="):
                # It's a formula — calculate it if possible
                calculated = _calculate_formula(tpl_value, cell_values, row_offset)
                if calculated is not None:
                    # Write the calculated value (Excel will recalc on open anyway)
                    xl_cell.value = calculated
                    # Computed by this writer from extracted values: no level
                    # of its own, so it is marked as one owing a look.
                    sm.mark(xl_cell, _review_status_unknown(calculated))
                    # Also store for downstream formula references
                    ref = f"{_col_letter(tc)}{tr+1}"
                    cell_values[ref] = calculated
                else:
                    # Write the formula with adjusted row offset for this block
                    adjusted = _adjust_formula_for_block(tpl_value, row_offset)
                    xl_cell.value = adjusted
            elif tpl_value:
                # A6 — only write non-empty static text; assigning "" materializes
                # an empty cell that reads back as a None column.
                xl_cell.value = tpl_value

            if cell_def.get("style"):
                _apply_cell_style(xl_cell, cell_def["style"], openpyxl_mod)

            merge_span = cell_def.get("mergeSpan") or merges_tpl.get(key)
            if merge_span:
                sr, sc = merge_span.get("rows",1), merge_span.get("cols",1)
                if sr > 1 or sc > 1:
                    try:
                        ws.merge_cells(
                            start_row=row_offset+tr+1, start_column=tc+1,
                            end_row=row_offset+tr+sr, end_column=tc+sc,
                        )
                    except Exception:
                        pass

        # Document separator between blocks — grey divider row
        if block_idx > 0:
            sep_base = row_offset - SEPARATOR_HEIGHT + 1  # 1-based
            # Grey shaded divider row
            for col_i in range(1, max_c + 3):
                _sep = ws.cell(row=sep_base + 3, column=col_i)
                if isinstance(_sep, MergedCell):
                    continue
                _sep.fill = PatternFill(fill_type="solid", fgColor="FFF3F4F6")
            lc = ws.cell(row=sep_base + 3, column=1)
            if not isinstance(lc, MergedCell):
                lc.value = f"Document {block_idx + 1}  ·  {doc_result.filename}"
                lc.font = Font(bold=True, color="FF374151", size=10)

        # ── Dynamic cells pass ────────────────────────────────────────────────────
        # Write any extracted_fields cells NOT already covered by cells_tpl entries.
        # This handles dynamic fill rows (e.g. balance sheet rows 1-8) where the
        # template has no cell definition but pdfplumber filled the values.
        written_refs = set()
        for key, cell_def in cells_tpl.items():
            if not isinstance(cell_def, dict) or cell_def.get("mergeParent"):
                continue
            parts = key.split(",")
            if len(parts) != 2:
                continue
            try:
                _tr2, _tc2 = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            written_refs.add(f"{_col_letter(_tc2)}{_tr2 + 1}")

        _dyn_written = 0
        for ef_ref, ef_val in extracted_fields.items():
            if not ef_ref or ef_ref in written_refs:
                continue
            _col_str = "".join(ch for ch in ef_ref if ch.isalpha()).upper()
            _row_str = "".join(ch for ch in ef_ref if ch.isdigit())
            if not _col_str or not _row_str:
                continue
            try:
                _tr2 = int(_row_str) - 1
                _tc2 = sum(
                    (ord(ch) - 64) * (26 ** i)
                    for i, ch in enumerate(reversed(_col_str))
                ) - 1
                if _tr2 < 0 or _tc2 < 0:
                    continue
            except (ValueError, IndexError):
                continue
            _xl = ws.cell(row=row_offset + _tr2 + 1, column=_tc2 + 1)
            # Skip merged-cell children — read-only, writing .value raises AttributeError
            if isinstance(_xl, MergedCell):
                continue
            _val = ef_val.get("value", "") if isinstance(ef_val, dict) else str(ef_val or "")
            _val = _val if _val is not None else ""
            try:
                _clean = str(_val).replace(",", "").replace("$", "").strip() if _val else ""
                if _clean and re.match(r'^-?[0-9]+\.?[0-9]*$', _clean):
                    _xl.value = float(_clean)
                    cell_values[ef_ref] = float(_clean)
                else:
                    _xl.value = _val or ""
            except (ValueError, AttributeError):
                _xl.value = _val or ""
            sm.field(_xl, extracted_data, ref=ef_ref, value=_val)
            _dyn_written += 1

        if _dyn_written:
            print(f"[EXPORT] form dynamic pass: {_dyn_written} extra cells written", flush=True)

        # ── table rows ───────────────────────────────────────────────────────────
        # The form loop above only handles single-value cells. Table rows go
        # after the template block so table data is never silently dropped.
        if extracted_data.get("table_rows"):
            _write_table_rows_fallback(ws, extracted_data,
                                       row_offset + max_r + 2, openpyxl_mod,
                                       marks=sm)

        # Flag count indicator
        flag_count = validation.get("flagged_count", 0)
        if flag_count > 0:
            nc = ws.cell(row=row_offset + 1, column=max_c + 2)
            if not isinstance(nc, MergedCell):
                nc.value = f"! {flag_count} low-confidence fields"
                nc.font = Font(color="FFDC2626", size=9, italic=True)

    print(f"[EXPORT] form: {len(doc_results)} blocks written", flush=True)


def _write_table_rows_fallback(ws, extracted_data, start_row, openpyxl_mod,
                               marks=None):
    """
    FIX 4 fallback — write table_rows when there is NO cell_binding_map table
    definition. Each row's values are placed sequentially into columns A, B, C, ...
    (row-dict order, skipping private _keys) starting at start_row (1-based), so
    extracted table data is never silently dropped. Skips merged-cell children.
    """
    from openpyxl.cell import MergedCell
    rows = [r for r in (extracted_data.get("table_rows") or []) if isinstance(r, dict)]
    if not rows:
        return
    sm = _marks_or_off(ws, marks)
    written = 0
    for i, row in enumerate(rows):
        out_row = start_row + i
        keys = [k for k in row if not str(k).startswith("_")]
        for c_idx, key in enumerate(keys):
            val = row[key]
            if isinstance(val, dict):
                val = val.get("value", "")
            xl = ws.cell(row=out_row, column=c_idx + 1)
            if isinstance(xl, MergedCell):
                continue
            sval = "" if val is None else str(val)
            clean = sval.replace(",", "").replace("$", "").replace("£", "") \
                        .replace("€", "").replace("₹", "").strip()
            if clean and re.match(r'^-?[0-9]+\.?[0-9]*$', clean):
                xl.value = float(clean) if "." in clean else int(clean)
            elif sval:
                xl.value = sval
            sm.row_cell(xl, extracted_data, row, key)
        written += 1
    if written:
        print(f"[EXPORT] table_rows fallback: {written} rows written (A/B/C...)", flush=True)


def _calculate_formula(formula: str, cell_values: dict, row_offset: int) -> Optional[float]:
    """
    Calculate simple Excel formulas using known cell values.
    Handles: =SUM(B9:B11), =SUM(B3,B5,B7), basic arithmetic.
    Returns calculated value or None if cannot calculate.
    """
    import re
    f = formula.strip()

    # =SUM(range) e.g. =SUM(B9:B11)
    sum_range = re.match(r'^=SUM\(([A-Z]+)(\d+):([A-Z]+)(\d+)\)$', f, re.IGNORECASE)
    if sum_range:
        col1, row1, col2, row2 = sum_range.groups()
        total = 0.0
        found_any = False
        for r in range(int(row1), int(row2) + 1):
            ref = f"{col1.upper()}{r}"
            if ref in cell_values:
                total += cell_values[ref]
                found_any = True
        return round(total, 2) if found_any else None

    # =SUM(B3,B5,B7) comma-separated
    sum_list = re.match(r'^=SUM\(([^)]+)\)$', f, re.IGNORECASE)
    if sum_list:
        refs = [r.strip() for r in sum_list.group(1).split(",")]
        total = 0.0
        found_any = False
        for ref in refs:
            if ref.upper() in cell_values:
                total += cell_values[ref.upper()]
                found_any = True
        return round(total, 2) if found_any else None

    return None


def _adjust_formula_for_block(formula: str, row_offset: int) -> str:
    """
    Adjust cell references in a formula for a block offset.
    =SUM(B9:B11) with offset 20 becomes =SUM(B29:B31)
    """
    import re
    if row_offset == 0:
        return formula

    def adjust_ref(match):
        col = match.group(1)
        row = int(match.group(2))
        return f"{col}{row + row_offset}"

    return re.sub(r'([A-Z]+)(\d+)', adjust_ref, formula)


def _write_mixed_excel(ws, doc_results, sheet_data, cells_tpl, max_r, max_c,
                        template_regions, openpyxl_mod, marks=None):
    """
    Mixed mode Excel writer.
    Handles: single table, multiple tables, tables anywhere in template.

    For each document block:
    1. Write form field rows (rows above the first table header)
    2. For each table region:
       a. Write the table header row from template
       b. Write all extracted data rows for that table
    3. Write any form rows that appear AFTER the last table (summary rows)
    4. Blank separator between document blocks
    """
    from openpyxl.styles import Font, PatternFill
    from openpyxl.cell import MergedCell
    sm = _marks_or_off(ws, marks)
    extracted_data = {}       # the current block's result; set in the main loop

    merges_tpl   = sheet_data.get("merges", {})
    table_regions = (template_regions or {}).get("table_regions", [])

    # Get section_label_rows from region analyser (authoritative source)
    # These are rows identified during template analysis as structural labels
    region_section_label_rows = set(
        (template_regions or {}).get("section_label_rows", set())
    )

    # Sort tables by position
    tables_sorted = sorted(table_regions, key=lambda t: (t["header_row"], t["start_col"]))

    # Build set of table header rows
    table_header_rows = set(t["header_row"] for t in tables_sorted)

    # Section label rows — use region analyser result, fall back to heuristic
    if region_section_label_rows:
        section_label_rows = region_section_label_rows
    else:
        # Fallback: rows directly above table headers with text but no extract targets
        section_label_rows = set()
        for tbl in tables_sorted:
            hr = tbl["header_row"]
            for r_above in range(max(0, hr - 2), hr):
                has_label = any(
                    cells_tpl.get(f"{r_above},{c}", {}).get("value", "")
                    for c in range(max_c + 1)
                )
                has_extract = any(
                    cells_tpl.get(f"{r_above},{c}", {}).get("extractTarget", False)
                    for c in range(max_c + 1)
                )
                if has_label and not has_extract:
                    section_label_rows.add(r_above)

    # Blank rows in the template between sections — skip in output
    blank_between_tables = set()
    if tables_sorted:
        first_table_row = tables_sorted[0]["header_row"]
        last_table_row  = tables_sorted[-1]["header_row"]
        for r in range(first_table_row, last_table_row + 1):
            if r in table_header_rows or r in section_label_rows:
                continue
            row_has_content = any(
                cells_tpl.get(f"{r},{c}", {}).get("value", "") or
                cells_tpl.get(f"{r},{c}", {}).get("extractTarget", False)
                for c in range(max_c + 1)
            )
            if not row_has_content:
                blank_between_tables.add(r)

    # Determine which template rows are "form rows" (above first table)
    first_table_row = tables_sorted[0]["header_row"] if tables_sorted else max_r + 1
    last_table_row  = tables_sorted[-1]["header_row"] if tables_sorted else -1

    # Sort all template cells by row
    sorted_cells = sorted(
        [(key, cell_def) for key, cell_def in cells_tpl.items()
         if isinstance(cell_def, dict) and not cell_def.get("mergeParent")],
        key=lambda x: (int(x[0].split(",")[0]), int(x[0].split(",")[1]))
    )

    def write_template_row(tr, current_row, extracted_fields, label_to_value,
                           confidence_map):
        """Write one template row at the given output row."""
        from openpyxl.cell import MergedCell
        for key, cell_def in sorted_cells:
            parts = key.split(",")
            if int(parts[0]) != tr:
                continue
            tc = int(parts[1])
            # A6 — skip cells outside the content bounding box
            if tc > max_c:
                continue
            tpl_value = cell_def.get("value", "").strip()
            xl_cell = ws.cell(row=current_row, column=tc + 1)

            # Skip cells that are already merged children — read-only in openpyxl
            if isinstance(xl_cell, MergedCell):
                continue

            ref = f"{_col_letter(tc)}{tr + 1}"
            if cell_def.get("extractTarget"):
                filled = extracted_fields.get(ref) or label_to_value.get(tpl_value, "")
                if isinstance(filled, dict):
                    filled = filled.get("value", "")
                try:
                    clean_filled = str(filled).replace(",", "").strip() if filled else ""
                    # Only convert to float for financial amount fields
                    # Never convert IDs, codes, reference numbers, routing numbers
                    amount_labels = {"amount","total","subtotal","balance","price",
                                    "cost","tax","freight","fee","charge","payment",
                                    "salary","gross","net","deduction","rate"}
                    label_lower = tpl_value.lower() if tpl_value else ""
                    is_amount = any(kw in label_lower for kw in amount_labels)
                    if filled and is_amount and re.match(r'^-?[0-9]+\.?[0-9]*$', clean_filled):
                        xl_cell.value = float(clean_filled)
                    else:
                        xl_cell.value = filled or ""
                except (ValueError, TypeError):
                    xl_cell.value = filled or ""
                if extracted_fields.get(ref):
                    sm.field(xl_cell, extracted_data, ref=ref, value=filled)
                else:
                    sm.field(xl_cell, extracted_data, label=tpl_value, value=filled)
            elif not tpl_value and ref in extracted_fields:
                # kv_pair value cell: empty in template but AI extracted a value
                kv_filled = extracted_fields.get(ref)
                if isinstance(kv_filled, dict):
                    kv_filled = kv_filled.get("value", "")
                kv_filled = kv_filled or ""
                try:
                    clean_kv = str(kv_filled).replace(",", "").strip() if kv_filled else ""
                    if clean_kv and re.match(r'^-?[0-9]+\.?[0-9]*$', clean_kv):
                        xl_cell.value = float(clean_kv)
                    else:
                        xl_cell.value = kv_filled
                except (ValueError, TypeError):
                    xl_cell.value = kv_filled
                sm.field(xl_cell, extracted_data, ref=ref, value=kv_filled)
            elif tpl_value.startswith("="):
                try:
                    xl_cell.value = tpl_value
                except AttributeError:
                    pass
            elif tpl_value:
                # A6 — only write non-empty static text (assigning "" materializes
                # an empty cell that reads back as a None column)
                try:
                    xl_cell.value = tpl_value
                except AttributeError:
                    pass

            if cell_def.get("style"):
                _apply_cell_style(xl_cell, cell_def["style"], openpyxl_mod)

            merge_span = cell_def.get("mergeSpan") or merges_tpl.get(key)
            if merge_span:
                sr = merge_span.get("rows", 1)
                sc = merge_span.get("cols", 1)
                if sr > 1 or sc > 1:
                    try:
                        ws.merge_cells(
                            start_row=current_row, start_column=tc + 1,
                            end_row=current_row + sr - 1, end_column=tc + sc,
                        )
                    except Exception:
                        pass

    def write_table_data_rows(table_rows, tbl, current_row):
        """Write extracted data rows for one table."""
        col_names  = tbl.get("column_names", [])
        start_col  = tbl.get("start_col", 0)
        col_indices = {name: (start_col + i) for i, name in enumerate(col_names)}
        section    = tbl.get("section_label", "")

        # Build source key for this table (matches _table_source set during collection)
        import re as _re
        source_key = _re.sub(r'[^a-z0-9]', '_', section.lower()).strip('_')

        # Priority 1: rows tagged with _table_source matching this table
        rows_with_source = [
            r for r in table_rows
            if isinstance(r, dict) and r.get("_table_source", "") == source_key
        ]

        if rows_with_source:
            rows_for_table = rows_with_source
        elif len(tables_sorted) == 1:
            # Single table — use all rows
            rows_for_table = [r for r in table_rows if isinstance(r, dict)]
        else:
            # Fall back: rows that have this table's first column filled
            first_col = col_names[0] if col_names else None
            rows_for_table = [
                r for r in table_rows
                if isinstance(r, dict) and first_col and r.get(first_col, "")
                and not r.get("_table_source")
            ]

        written = 0
        for row_data in rows_for_table:
            # Skip rows that are headers or section labels
            row_vals = [str(v).strip() for v in row_data.values()
                       if v and not str(v).startswith("_")]
            if all(v in col_names or v == section for v in row_vals if v):
                continue

            for col_name, c_idx in col_indices.items():
                val = row_data.get(col_name, "")
                if isinstance(val, dict):
                    val = val.get("value", "")
                val = str(val).strip() if val is not None else ""
                if val in col_names:
                    val = ""
                xl_cell = ws.cell(row=current_row, column=c_idx + 1)
                if isinstance(xl_cell, MergedCell):
                    continue
                try:
                    clean = val.replace(",", "").replace("$", "").replace("£", "").strip()
                    amount_labels = {"amount","total","subtotal","balance","price",
                                    "cost","tax","freight","fee","charge","payment",
                                    "salary","gross","net","deduction","rate","qty","quantity"}
                    col_lower = col_name.lower()
                    is_amount = any(kw in col_lower for kw in amount_labels)
                    if clean and clean not in ("", "-") and is_amount and re.match(r'^-?[0-9]+\.?[0-9]*$', clean):
                        xl_cell.value = float(clean)
                    else:
                        xl_cell.value = val or ""
                except (ValueError, TypeError):
                    xl_cell.value = val
                if val:
                    sm.row_cell(xl_cell, extracted_data, row_data, col_name)
            current_row += 1
            written += 1

        return current_row, written

    # ── Main write loop ───────────────────────────────────────────────────────
    current_output_row = 1

    for block_idx, doc_result in enumerate(doc_results):
        extracted_data   = doc_result.get_extracted_data()
        extracted_fields = extracted_data.get("extracted_fields", {})
        validation       = extracted_data.get("validation", {})
        confidence_map   = validation.get("confidence_map", {})
        table_rows       = extracted_data.get("table_rows", [])

        label_to_value = {
            k: (v.get("value", "") if isinstance(v, dict) else str(v or ""))
            for k, v in extracted_data.get("extracted_data", {}).items()
            if not k.startswith("_label_")
        }

        block_start_row = current_output_row

        # Document separator for multi-doc jobs
        # 3 blank rows + a clear divider line so document boundaries are obvious
        if block_idx > 0:
            # 3 blank rows to separate documents (vs 1 row between tables)
            current_output_row += 3

            # Divider row with filename — styled distinctly from table separators
            for col_i in range(1, max_c + 3):
                div_cell = ws.cell(row=current_output_row, column=col_i)
                if isinstance(div_cell, MergedCell):
                    continue
                div_cell.fill = PatternFill(fill_type="solid", fgColor="FFE5E7EB")
            lc = ws.cell(row=current_output_row, column=1)
            if not isinstance(lc, MergedCell):
                lc.value = f"Document: {doc_result.filename}"
                lc.font = Font(bold=True, color="FF1F2937", size=10)
            current_output_row += 1
            # 1 more blank row after the divider before content starts
            current_output_row += 1

        # Track which output row each template row maps to
        template_row_to_output = {}

        # Step 1: Write form rows ABOVE first table
        # Skip: section label rows (written in Step 2 before each table header)
        #        blank rows between sections
        for tr in range(min(first_table_row, max_r + 1)):
            if tr in section_label_rows or tr in blank_between_tables:
                # Skip — section labels are written in Step 2 before their table
                continue
            write_template_row(tr, current_output_row, extracted_fields,
                               label_to_value, confidence_map)
            template_row_to_output[tr] = current_output_row
            current_output_row += 1

        # Step 2: For each table — write section label, then header, then data rows
        for tbl_idx, tbl in enumerate(tables_sorted):
            hr = tbl["header_row"]

            # Fixed 1-row gap before each table (not the template's variable gap)
            # This ensures consistent spacing regardless of how many blank rows
            # the user left in the template between tables
            if tbl_idx > 0:
                current_output_row += 1  # exactly 1 blank row between tables

            # Write section label row(s) immediately before this table header
            # Only look 2 rows above — matching the detection window above
            for r_label in range(max(0, hr - 2), hr):
                if r_label in section_label_rows:
                    write_template_row(r_label, current_output_row, extracted_fields,
                                      label_to_value, confidence_map)
                    current_output_row += 1

            # Write table header row from template (column names row)
            write_template_row(hr, current_output_row, extracted_fields,
                               label_to_value, confidence_map)
            current_output_row += 1

            # Write data rows for this table
            current_output_row, n_rows = write_table_data_rows(
                table_rows, tbl, current_output_row
            )

            # If no rows extracted — write one blank placeholder row
            if n_rows == 0:
                current_output_row += 1

        # Step 3: Write form rows AFTER the last table (summary/totals)
        for tr in range(last_table_row + 1, max_r + 1):
            if tr in blank_between_tables:
                current_output_row += 1
                continue
            write_template_row(tr, current_output_row, extracted_fields,
                               label_to_value, confidence_map)
            template_row_to_output[tr] = current_output_row
            current_output_row += 1

        # ── Dynamic cells pass (mixed mode) ──────────────────────────────────────
        # Write extracted_fields cells that fell in blank_between_tables rows
        # and were therefore skipped by the main write loop.
        _written_m = set()
        for key, cell_def in cells_tpl.items():
            if not isinstance(cell_def, dict) or cell_def.get("mergeParent"):
                continue
            parts = key.split(",")
            if len(parts) != 2:
                continue
            try:
                _tr2, _tc2 = int(parts[0]), int(parts[1])
            except ValueError:
                continue
            _written_m.add(f"{_col_letter(_tc2)}{_tr2 + 1}")

        _dyn_written_m = 0
        for ef_ref, ef_val in extracted_fields.items():
            if not ef_ref or ef_ref in _written_m:
                continue
            _col_str = "".join(ch for ch in ef_ref if ch.isalpha()).upper()
            _row_str = "".join(ch for ch in ef_ref if ch.isdigit())
            if not _col_str or not _row_str:
                continue
            try:
                _tr2 = int(_row_str) - 1
                _tc2 = sum(
                    (ord(ch) - 64) * (26 ** i)
                    for i, ch in enumerate(reversed(_col_str))
                ) - 1
                if _tr2 < 0 or _tc2 < 0:
                    continue
            except (ValueError, IndexError):
                continue
            # Find nearest written template row above to anchor output position
            _preceding = [r for r in template_row_to_output if r < _tr2]
            if not _preceding:
                continue
            _anchor_tpl = max(_preceding)
            _anchor_out = template_row_to_output[_anchor_tpl]
            _out_row2 = _anchor_out + (_tr2 - _anchor_tpl)
            _xl = ws.cell(row=_out_row2, column=_tc2 + 1)
            # Skip merged-cell children — read-only, writing .value raises AttributeError
            if isinstance(_xl, MergedCell):
                continue
            _val = ef_val.get("value", "") if isinstance(ef_val, dict) else str(ef_val or "")
            _val = _val if _val is not None else ""
            try:
                _clean = str(_val).replace(",", "").replace("$", "").strip() if _val else ""
                if _clean and re.match(r'^-?[0-9]+\.?[0-9]*$', _clean):
                    _xl.value = float(_clean)
                else:
                    _xl.value = _val or ""
            except (ValueError, AttributeError):
                _xl.value = _val or ""
            sm.field(_xl, extracted_data, ref=ef_ref, value=_val)
            _dyn_written_m += 1

        if _dyn_written_m:
            print(f"[EXPORT] mixed dynamic pass: {_dyn_written_m} extra cells written", flush=True)

        # Flag indicator
        flag_count = validation.get("flagged_count", 0)
        if flag_count > 0:
            nc = ws.cell(row=block_start_row, column=max_c + 2)
            if not isinstance(nc, MergedCell):
                nc.value = f"! {flag_count} low-confidence"
                nc.font = Font(color="FFDC2626", size=9, italic=True)

        # No trailing blank row here — spacing is added at the START of the next block
        # (3 blank rows for new document, 1 blank row between tables within same doc)

    print(f"[EXPORT] mixed: {len(doc_results)} blocks, "
          f"{current_output_row} total rows written", flush=True)


def _write_flat_table(ws, doc_results, openpyxl_mod, show_filename=True,
                      marks=True):
    """Fallback flat table when no template.

    `show_filename=False` drops the Filename column. It is what a demo export
    passes: the stored filename of a document uploaded to the object store is a
    TEMP NAME (`tmphjtbr12o.pdf` — see `storage.get_local_path`), and a column
    of those is worse than no column at all in front of an audience.
    """
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter
    all_keys, seen = [], set()
    for dr in doc_results:
        for k in (dr.get_extracted_data().get("extracted_data") or {}):
            if k not in seen and not k.startswith("_label_"):
                seen.add(k); all_keys.append(k)
    hf = PatternFill(fill_type="solid", fgColor="FF4F46E5")
    hfont = Font(bold=True, color="FFFFFFFF", size=11)
    from app.core.export_marks import SheetMarks
    sm = SheetMarks(ws, enabled=marks)
    first = 1
    if show_filename:
        c = ws.cell(row=1, column=1, value="Filename"); c.font=hfont; c.fill=hf
        c = ws.cell(row=1, column=2, value="Page"); c.font=hfont; c.fill=hf
        first = 3
    for ci, key in enumerate(all_keys, first):
        c = ws.cell(row=1, column=ci, value=key); c.font=hfont; c.fill=hf
    for ri, dr in enumerate(doc_results, 2):
        if show_filename:
            ws.cell(row=ri, column=1, value=dr.filename)
            pages = dr.get_extracted_data().get("source_pages") or []
            if len(pages) >= 2 and pages[0] == pages[-1]:
                shown_page = pages[0]
            elif len(pages) >= 2:
                shown_page = f"{pages[0]}-{pages[-1]}"
            elif pages:
                shown_page = pages[0]
            else:
                shown_page = None
            ws.cell(row=ri, column=2, value=shown_page)
        ed = dr.get_extracted_data()
        inner = ed.get("extracted_data") or {}
        for ci, key in enumerate(all_keys, first):
            v = inner.get(key)
            c = ws.cell(row=ri, column=ci, value=(v.get("value","") if isinstance(v,dict) else (v or "")))
            if key in inner:
                sm.field(c, ed, ref=(v.get("ref") if isinstance(v, dict) else None),
                         label=key)
    if show_filename:
        ws.column_dimensions["A"].width = 30
        ws.column_dimensions["B"].width = 12
    for ci in range(first, len(all_keys)+first):
        ws.column_dimensions[get_column_letter(ci)].width = 20
    sm.finish()
