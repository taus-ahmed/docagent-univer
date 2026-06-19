"""
Test pdfplumber dynamic-fill extraction for the balance sheet template.

Simulates what _pdfplumber_extract_dynamic_parallel would do for a parallel-column
template whose data rows are empty placeholders.

Expected results (some values):
  B2=168000  B3=428000  B4=724000  B5=50000  B6=17400
  D2=262000  D3=-139800  D4=85000  D5=14000
"""
import re
import sys
import json
from pathlib import Path

PDF_PATH = (
    r"C:\Users\Admin\AppData\Roaming\Claude\local-agent-mode-sessions"
    r"\767666a9-af0f-4e59-aa65-7b4c1c6a5838\858fc626-855e-4992-8820-dd85e8548030"
    r"\agent\local_ditto_858fc626-855e-4992-8820-dd85e8548030\uploads"
    r"\556aba54-BS2024PROJYE.pdf"
)

# ---------------------------------------------------------------------------
# Minimal re-implementation of the key helpers so we can run stand-alone
# ---------------------------------------------------------------------------

def _cell_ref(r: int, c: int) -> str:
    col_letter = ""
    n = c
    while True:
        col_letter = chr(65 + (n % 26)) + col_letter
        n = n // 26 - 1
        if n < 0:
            break
    return f"{col_letter}{r + 1}"


def _pdfplumber_extract_dynamic_parallel(doc_text: str, regions: dict, layout: dict) -> dict:
    """Copied from extract.py after the fix."""
    para_groups = regions.get("parallel_column_groups", [])
    if not para_groups:
        return {}

    cells = layout.get("cells", {})
    if not cells:
        return {}

    compact_grid: dict = {}
    max_row = 0
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
        raw_val = cell.get("value")
        val_str = str(raw_val).strip() if raw_val is not None else ""
        if val_str:
            compact_grid[(r, c)] = val_str

    dynamic_zones = []

    for pg in para_groups:
        label_col = pg["label_col"]
        value_col = pg["value_col"]

        label_rows = [
            (r, compact_grid[(r, label_col)])
            for r in range(max_row + 1)
            if compact_grid.get((r, label_col), "")
        ]

        if len(label_rows) < 2:
            continue

        for i in range(len(label_rows) - 1):
            curr_r, curr_val = label_rows[i]
            next_r, next_val = label_rows[i + 1]

            empty_span = next_r - curr_r - 1
            if empty_span < 2:
                continue

            curr_lc = curr_val.lower().strip()
            is_total = curr_lc in ("total", "grand total", "subtotal", "final total")

            if is_total:
                next_lc = next_val.lower().strip()
                if next_lc in ("total", "grand total", "subtotal", "final total"):
                    continue
                zone_label = next_val
            else:
                zone_label = curr_val

            fill_rows = list(range(curr_r + 1, next_r))
            dynamic_zones.append({
                "group":      pg,
                "zone_label": zone_label,
                "label_col":  label_col,
                "value_col":  value_col,
                "fill_rows":  fill_rows,
            })

    if not dynamic_zones:
        print("No dynamic zones found")
        return {}

    print(f"\n=== DYNAMIC ZONES ({len(dynamic_zones)}) ===")
    for z in dynamic_zones:
        cols = f"col {chr(65+z['label_col'])}-{chr(65+z['value_col'])}"
        print(f"  '{z['zone_label']}' {cols} -> rows {z['fill_rows'][0]+1}..{z['fill_rows'][-1]+1} ({len(z['fill_rows'])} slots)")

    zone_labels = list({z["zone_label"] for z in dynamic_zones})

    def _norm(s: str) -> str:
        n = re.sub(r'[^\w\s]', ' ', s)
        return re.sub(r'\s+', ' ', n).lower().strip()

    norm_zone_map = {_norm(lbl): lbl for lbl in zone_labels if lbl}

    val_re_dyn = re.compile(
        r'^(.*?)\s+\(?\$?([-]?[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{0,2})?)\)?$'
    )
    tab_re_dyn = re.compile(
        r'^(.*?)\t\$?([-]?[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]{0,2})?)$'
    )

    current_section: str = None
    pdf_sections: dict = {}

    for raw_line in doc_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("---"):
            continue

        norm_line = _norm(line)
        norm_line_words = set(norm_line.split())
        matched = None
        best_score = 0.0
        for norm_lbl, orig_lbl in norm_zone_map.items():
            if not norm_lbl:
                continue
            norm_lbl_words = set(norm_lbl.split())
            if not norm_lbl_words or not norm_line_words:
                continue
            wc_ratio = min(len(norm_lbl_words), len(norm_line_words)) / max(len(norm_lbl_words), len(norm_line_words))
            if wc_ratio < 0.7:
                continue
            intersection = norm_lbl_words & norm_line_words
            union = norm_lbl_words | norm_line_words
            score = len(intersection) / len(union) if union else 0.0
            if score >= 0.5 and score > best_score:
                best_score = score
                matched = orig_lbl

        if matched:
            current_section = matched
            pdf_sections.setdefault(current_section, [])
            continue

        if current_section is None:
            continue

        m = tab_re_dyn.match(line) or val_re_dyn.match(line)
        if not m:
            # Unrecognised section heading (>50% uppercase) → close current section
            alpha_chars = [ch for ch in line if ch.isalpha()]
            if alpha_chars and sum(1 for ch in alpha_chars if ch.isupper()) / len(alpha_chars) > 0.5:
                current_section = None
            continue

        lbl_raw = m.group(1).strip().rstrip(":").strip()
        val_raw = m.group(2).strip().lstrip("$").strip()
        if not lbl_raw or not val_raw:
            continue

        norm_item = _norm(lbl_raw)
        if (norm_item in ("total", "grand total", "subtotal")
                or norm_item.startswith("total ")
                or "subtotal" in norm_item):
            current_section = None  # close section after its total row
            continue

        val_clean = val_raw.replace(",", "")
        if re.search(r'\(\$?[\d,]+(?:\.\d{1,2})?\)', line) and not val_clean.startswith("-"):
            val_clean = "-" + val_clean

        if lbl_raw.lower().startswith(("less:", "less ", "less-")):
            if not val_clean.startswith("-"):
                val_clean = "-" + val_clean

        pdf_sections[current_section].append((lbl_raw, val_clean))

    print(f"\n=== PDF SECTIONS PARSED ===")
    for sec_name, items in pdf_sections.items():
        print(f"  '{sec_name}': {len(items)} items")
        for lbl, val in items:
            print(f"    {lbl!r}: {val}")

    extracted_fields: dict = {}

    for zone in dynamic_zones:
        zone_label = zone["zone_label"]
        label_col  = zone["label_col"]
        value_col  = zone["value_col"]
        fill_rows  = zone["fill_rows"]

        norm_zone = _norm(zone_label)
        norm_zone_words = set(norm_zone.split())
        pdf_items = None
        best_score = 0.0
        for pdf_sec_name, items in pdf_sections.items():
            norm_pdf = _norm(pdf_sec_name)
            norm_pdf_words = set(norm_pdf.split())
            if not norm_zone_words or not norm_pdf_words:
                continue
            wc_ratio = min(len(norm_zone_words), len(norm_pdf_words)) / max(len(norm_zone_words), len(norm_pdf_words))
            if wc_ratio < 0.7:
                continue
            intersection = norm_zone_words & norm_pdf_words
            union = norm_zone_words | norm_pdf_words
            score = len(intersection) / len(union) if union else 0.0
            if score >= 0.6 and score > best_score:
                best_score = score
                pdf_items = items

        if not pdf_items:
            print(f"  [WARN] no PDF match for zone '{zone_label}'")
            continue

        for slot_idx, (item_label, item_value) in enumerate(pdf_items):
            if slot_idx >= len(fill_rows):
                break
            row = fill_rows[slot_idx]
            label_ref = _cell_ref(row, label_col)
            value_ref = _cell_ref(row, value_col)
            extracted_fields[label_ref] = {"value": item_label,  "confidence": "high"}
            extracted_fields[value_ref] = {"value": item_value,  "confidence": "high"}

    return extracted_fields


# ---------------------------------------------------------------------------
# Build a synthetic template matching the BS structure from the problem spec
# ---------------------------------------------------------------------------

def make_bs_layout() -> dict:
    """
    Simulate the balance sheet template layout JSON.

    Row 0:  A="Current assets" | B="Amount" | C="Non current assets" | D="Amount"
    Rows 1-8: empty
    Row 9:  A="Total" | C="Total" | E="Final Total"  (B, D, F empty)
    Row 10: A="Current liabilities" | C="Non current liabilities"
    Rows 11-19: empty
    Row 20: A="Total" | C="Total" | E="Final Total"  (B, D, F empty)
    """
    cells = {}

    def add(r, c, value):
        cells[f"{r},{c}"] = {"value": value, "extractTarget": False}

    def add_empty(r, c):
        cells[f"{r},{c}"] = {"value": "", "extractTarget": False}

    # Row 0: headers
    add(0, 0, "Current assets")
    add(0, 1, "Amount")
    add(0, 2, "Non current assets")
    add(0, 3, "Amount")

    # Rows 1-8: empty data rows for current/non-current assets
    for r in range(1, 9):
        for c in range(4):
            add_empty(r, c)

    # Row 9: Total row
    add(9, 0, "Total"); add_empty(9, 1)
    add(9, 2, "Total"); add_empty(9, 3)
    add(9, 4, "Final Total"); add_empty(9, 5)

    # Row 10: section headers for liabilities
    add(10, 0, "Current liabilities"); add_empty(10, 1)
    add(10, 2, "Non current liabilities"); add_empty(10, 3)

    # Rows 11-19: empty data rows for liabilities
    for r in range(11, 20):
        for c in range(4):
            add_empty(r, c)

    # Row 20: Total row
    add(20, 0, "Total"); add_empty(20, 1)
    add(20, 2, "Total"); add_empty(20, 3)
    add(20, 4, "Final Total"); add_empty(20, 5)

    return {"cells": cells, "extractTargets": []}


def make_bs_regions(layout: dict) -> dict:
    """
    Build the regions dict that _analyse_template_regions would produce.
    Manually constructed to match the balance sheet template structure.
    """
    # kv_pairs come from rows with label+empty-next-col: rows 9, 10, 20
    kv_pairs = [
        {"label": "Total",                   "value_ref": "B10", "row": 9},
        {"label": "Total",                   "value_ref": "D10", "row": 9},
        {"label": "Final Total",             "value_ref": "F10", "row": 9},
        {"label": "Current liabilities",     "value_ref": "B11", "row": 10},
        {"label": "Non current liabilities", "value_ref": "D11", "row": 10},
        {"label": "Total",                   "value_ref": "B21", "row": 20},
        {"label": "Total",                   "value_ref": "D21", "row": 20},
        {"label": "Final Total",             "value_ref": "F21", "row": 20},
    ]

    # parallel_column_groups: group by label col
    # Group 1 (A→B): rows 9, 10, 20
    # Group 2 (C→D): rows 9, 10, 20
    group1_items = [
        {"label": "Total",               "label_ref": "A10", "value_ref": "B10", "row": 9},
        {"label": "Current liabilities", "label_ref": "A11", "value_ref": "B11", "row": 10},
        {"label": "Total",               "label_ref": "A21", "value_ref": "B21", "row": 20},
    ]
    group2_items = [
        {"label": "Total",                    "label_ref": "C10", "value_ref": "D10", "row": 9},
        {"label": "Non current liabilities",  "label_ref": "C11", "value_ref": "D11", "row": 10},
        {"label": "Total",                    "label_ref": "C21", "value_ref": "D21", "row": 20},
    ]

    parallel_groups = [
        {
            "group_id": 1,
            "label_col": 0,
            "value_col": 1,
            "label_col_letter": "A",
            "value_col_letter": "B",
            "section_label": "Current assets",
            "items": group1_items,
        },
        {
            "group_id": 2,
            "label_col": 2,
            "value_col": 3,
            "label_col_letter": "C",
            "value_col_letter": "D",
            "section_label": "Non current assets",
            "items": group2_items,
        },
    ]

    return {
        "primary_mode": "parallel_groups",
        "kv_pairs": kv_pairs,
        "parallel_column_groups": parallel_groups,
        "explicit_targets": [],
        "table_regions": [],
        "two_col_pairs": [],
        "transposed_tables": [],
        "section_label_rows": set(),
        "has_explicit_targets": False,
        "has_table": False,
        "max_row": 20,
        "max_col": 5,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    try:
        import pdfplumber
    except ImportError:
        print("pdfplumber not installed — install with: pip install pdfplumber")
        sys.exit(1)

    pdf_path = Path(PDF_PATH)
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        sys.exit(1)

    print(f"=== Extracting text from: {pdf_path.name} ===")
    with pdfplumber.open(str(pdf_path)) as pdf:
        pages_text = []
        for i, page in enumerate(pdf.pages):
            txt = page.extract_text() or ""
            pages_text.append(txt)
            print(f"\n--- PAGE {i+1} ({len(txt)} chars) ---")
            print(txt[:2000] if len(txt) > 2000 else txt)
        doc_text = "\n--- PAGE BREAK ---\n".join(pages_text)

    print("\n\n=== RUNNING DYNAMIC EXTRACTION ===")
    layout  = make_bs_layout()
    regions = make_bs_regions(layout)

    result = _pdfplumber_extract_dynamic_parallel(doc_text, regions, layout)

    print(f"\n=== EXTRACTED FIELDS ({len(result)}) ===")
    # Sort by cell ref for readable output
    for ref in sorted(result.keys(), key=lambda r: (r[0], int(r[1:]) if r[1:].isdigit() else 0)):
        val = result[ref]
        print(f"  {ref:5s} = {val['value']!r:30s}  ({val['confidence']})")

    # Verify expected values
    print("\n=== EXPECTED VALUE CHECKS ===")
    expected = {
        "B2": "168000",
        "B3": "428000",
        "B4": "724000",
        "B5": "50000",
        "B6": "17400",
        "D2": "262000",
        "D3": "-139800",
        "D4": "85000",
        "D5": "14000",
    }
    all_ok = True
    for ref, expected_val in expected.items():
        actual = result.get(ref, {}).get("value", "MISSING")
        ok = actual == expected_val
        status = "OK" if ok else "FAIL"
        print(f"  [{status}] {ref}: expected={expected_val!r} actual={actual!r}")
        if not ok:
            all_ok = False

    print(f"\n{'ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
