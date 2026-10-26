"""The vision-first prompt builder used by the image path.

Moved verbatim from app/api/routes/extract.py (round 13); extract.py re-exports every name.
"""

import app.services.paths  # noqa: F401  (engine on sys.path)
from app.services.template_parsing import _cell_ref
from app.services.template_parsing import _col_letter
from app.services.template_parsing import _get_system_prompt
from app.services.template_parsing import _get_table_rules
from app.services.template_parsing import _get_unguided_prompt
from log_safety import exc_brief
import json
import re
# --imports-end--


def _smart_truncate(doc_text: str, primary_mode: str, regions: dict) -> str:
    """
    Smart text truncation for long documents.
    Also replaces the PAGE BREAK marker with an explicit label the AI understands.
    """
    if not doc_text:
        return ""

    MAX_FORM  = 3000
    MAX_TABLE = 8000

    # Replace page break marker with explicit AI-readable label
    # This is critical — the AI must know content continues on next page
    doc_text = doc_text.replace(
        "--- PAGE BREAK ---",
        "\n\n=== DOCUMENT CONTINUES ON NEXT PAGE — ALL CONTENT BELOW IS PART OF THE SAME DOCUMENT ===\n\n"
    )

    # Short doc — no truncation needed
    if len(doc_text) <= MAX_TABLE:
        return doc_text

    if primary_mode in ("form_with_targets", "form_kv"):
        return doc_text[:MAX_FORM]

    # For table/mixed — smart extraction
    table_regions = regions.get("table_regions", [])
    lines = doc_text.split('\n')

    # Always include first 1500 chars for header fields
    header_text = doc_text[:1500]
    collected   = [header_text]
    used_chars  = len(header_text)

    if table_regions:
        for tr in table_regions:
            col_names   = tr.get("column_names", [])
            section_lbl = tr.get("section_label", "")
            if not col_names:
                continue

            section_start = -1
            search_terms  = col_names[:2] + ([section_lbl] if section_lbl else [])

            for i, line in enumerate(lines):
                if any(term.lower() in line.lower() for term in search_terms if term):
                    section_start = i
                    break

            if section_start == -1:
                continue

            section_lines = lines[section_start:section_start + 100]
            section_text  = '\n'.join(section_lines)

            budget = min(2000, MAX_TABLE - used_chars - 100)
            if budget <= 0:
                break

            snippet = section_text[:budget]
            collected.append(f"\n--- SECTION: {section_lbl or 'Table'} ---\n{snippet}")
            used_chars += len(snippet)

    result = '\n'.join(collected)

    if used_chars < MAX_TABLE:
        remaining = doc_text[1500:MAX_TABLE - used_chars + 1500]
        result += '\n' + remaining

    return result[:MAX_TABLE]


def _build_page_anchor_map(doc_text: str, table_regions: list) -> dict:
    """
    Scan document text to find which page each table's content appears on.
    Searches for: section label name, column header names, and common synonyms.
    Zero hardcoding — purely derived from template structure vs document text.

    Returns: {section_label: page_number}
    """
    if not doc_text or not table_regions:
        return {}

    pages = doc_text.split("--- PAGE BREAK ---")
    if len(pages) <= 1:
        return {}

    page_map = {}
    for tbl in table_regions:
        section   = tbl.get("section_label", "")
        col_names = tbl.get("column_names", [])
        if not col_names and not section:
            continue

        # Build search terms:
        # 1. Section label words (e.g. "Earning Table" -> ["earning", "table"])
        # 2. Column header names
        # 3. First word of each column name (catches "Earning Type" -> "earning")
        search_terms = set()
        if section:
            for word in section.lower().split():
                if len(word) > 3:  # skip short words like "and", "the"
                    search_terms.add(word)
        for col in col_names:
            search_terms.add(col.lower())
            first_word = col.lower().split()[0] if col else ""
            if len(first_word) > 3:
                search_terms.add(first_word)

        # Score each page by how many search terms appear
        best_page  = 0
        best_score = 0
        for page_num, page_text in enumerate(pages, 1):
            page_lower = page_text.lower()
            score = sum(1 for term in search_terms if term in page_lower)
            if score > best_score:
                best_score = score
                best_page  = page_num

        # Only anchor if we found a meaningful match
        if best_page > 0 and best_score > 0:
            page_map[section] = best_page

    # If all tables map to the same page, anchoring adds no value — skip it
    unique_pages = set(page_map.values())
    if len(unique_pages) <= 1:
        # Try to differentiate by finding where the MOST table-specific content is
        # Use the LAST significant keyword from each table's columns
        page_map_refined = {}
        for tbl in table_regions:
            section   = tbl.get("section_label", "")
            col_names = tbl.get("column_names", [])
            if not section or not col_names:
                continue
            # Use the last column name as a differentiator
            # (first col is often shared, e.g. "Amount" appears in both tables)
            differentiator = col_names[-1].lower() if len(col_names) > 1 else col_names[0].lower()
            # Also try section label first word
            sec_word = section.lower().split()[0] if section else ""

            best_page  = 0
            best_score = 0
            for page_num, page_text in enumerate(pages, 1):
                page_lower = page_text.lower()
                score = (
                    (2 if sec_word and sec_word in page_lower else 0) +
                    (1 if differentiator in page_lower else 0)
                )
                if score > best_score:
                    best_score = score
                    best_page  = page_num
            if best_page > 0:
                page_map_refined[section] = best_page

        # Use refined map if it produces different pages
        if len(set(page_map_refined.values())) > 1:
            return page_map_refined

    return page_map


_TEMPLATE_UNDERSTANDING_SYSTEM = (
    "You are an expert at analyzing spreadsheet templates that users design to "
    "extract structured data from business documents. You understand labels, "
    "section headers, column headers, and which blank cells are meant to receive "
    "extracted values."
)


# L1 — semantic aliases for commonly re-labeled fields. A template says
# "Contract" while the document says "PO Ref"; without an alias hint Gemini
# returns "". Matched against the cell's data_type OR label keywords (first
# matching entry wins). Generic — applies to any template/document type.
_CBM_FIELD_ALIASES = (
    {"data_types": ("contract_number", "reference_number", "po_number", "order_reference"),
     "label_kw": (r"\bcontract\b", r"\breference\b", r"\bref\b", r"\bpo\b", r"\border\s*no\b"),
     "note": "May appear as: PO Number, PO Ref, Purchase Order, Contract Number, "
             "Reference Number, Order Reference"},
    {"data_types": ("company_name", "organization_name"),
     "label_kw": (r"\bcompany\b", r"\borgani[sz]ation\b", r"\bfirm\b"),
     "note": "May appear as: Company, Organization, Firm, Business, Corp, LLC, Ltd, Inc"},
    {"data_types": ("invoice_number",),
     "label_kw": (r"\binvoice\b", r"\binv\b", r"\bbill\s*no\b"),
     "note": "May appear as: Invoice #, Inv No, Invoice Number, Reference, Bill Number"},
)


def _build_layout_prompt_parts(binding_map: dict, layout: dict, doc_text: str,
                               system_instruction: str) -> tuple:
    """
    COMPONENT 4 — build the "extract & place" prompt for layout templates. Uses the
    section-aware column_groups from the binding map so EVERY vertical section
    (side-by-side AND stacked) is described with its own explicit row range.
    """
    import re as _re
    meta           = binding_map.get("_meta", {})
    column_groups  = meta.get("column_groups", [])
    col_headers    = meta.get("column_headers", {})

    # Fallback: derive minimal groups if column_groups is unexpectedly empty.
    if not column_groups:
        td_cols = sorted({b["col_index"] for b in binding_map.values()
                          if isinstance(b, dict) and b.get("role") == "table_data"
                          and isinstance(b.get("col_index"), int)})
        for i in range(0, len(td_cols), 2):
            lc = td_cols[i]
            vc = td_cols[i + 1] if i + 1 < len(td_cols) else None
            if vc is None:
                continue
            rows = sorted(int(k.split(",")[0]) for k, b in binding_map.items()
                          if isinstance(b, dict) and b.get("role") == "table_data"
                          and b.get("col_index") == vc)
            if rows:
                column_groups.append({
                    "group_id": i // 2 + 1,
                    "section_label": str(col_headers.get(lc, col_headers.get(str(lc), "")) or f"section_{i}"),
                    "label_col_letter": _col_letter(lc), "value_col_letter": _col_letter(vc),
                    "start_row": rows[0], "end_row": rows[-1],
                })

    fixed = sorted(
        (_cell_ref(*map(int, k.split(","))), b["label"])
        for k, b in binding_map.items()
        if isinstance(b, dict) and b.get("role") == "value_target" and b.get("label")
    )

    desc = [
        "=== EXTRACTION TASK (LAYOUT MODE) ===",
        "This template provides a LAYOUT, not a fixed field list. The line-item rows "
        "are BLANK. Read the document, extract ALL line items (both the item NAME and "
        "its AMOUNT) for EACH section below, and place them into the grid. Each section "
        "has its OWN row range and columns — keep sections separate.",
        "",
    ]
    out_sections, _seen_slugs = [], {}
    _col_first_use = {}        # (label_col, value_col) -> first section that used it
    _all_cols = []             # every unique column letter used, in order
    for g in column_groups:
        sec_label = g.get("section_label") or f"section_{g.get('group_id', 0)}"
        lcl = (g.get("label_col_letter") or "").upper()
        vcl = (g.get("value_col_letter") or "").upper()
        start_ss = int(g.get("start_row", 0)) + 1     # 1-based spreadsheet rows
        end_ss   = int(g.get("end_row", 0)) + 1
        slug = _re.sub(r'[^a-z0-9]+', '_', sec_label.lower()).strip('_') or f"section_{g.get('group_id', 0)}"
        if slug in _seen_slugs:
            _seen_slugs[slug] += 1; slug = f"{slug}_{_seen_slugs[slug]}"
        else:
            _seen_slugs[slug] = 1
        for col in (lcl, vcl):
            if col and col not in _all_cols:
                _all_cols.append(col)
        desc.append(f'SECTION: "{sec_label}" (rows {start_ss} to {end_ss})')
        desc.append(f'  Column {lcl} = labels, Column {vcl} = values')
        desc.append(f'  MANDATORY: Extract EVERY individual line item found in the '
                    f'"{sec_label}" portion of the document. Each line item gets its '
                    f'own row (name into column {lcl}, amount into column {vcl}, rows '
                    f'{start_ss}-{end_ss}). The section TOTAL goes in the fixed cell '
                    f'listed below — NOT in this section\'s rows.')
        # FIX 1: when this section reuses columns from an earlier section, say so.
        prev = _col_first_use.get((lcl, vcl))
        if prev:
            desc.append(f'  NOTE: This section uses the SAME columns ({lcl}/{vcl}) as '
                        f'"{prev}". Reuse those columns — do NOT create new columns.')
        else:
            _col_first_use[(lcl, vcl)] = sec_label
        desc.append(f'  This section MUST be present in your response with at least one '
                    f'row. Do not skip any section.')
        desc.append("")
        out_sections.append((slug, lcl, vcl, start_ss))

    # FIX 1 + completeness: global directives inserted at the TOP, before sections.
    if out_sections:
        _names = ", ".join(f'"{s[0]}"' for s in out_sections)
        desc.insert(3, f'COLUMN CONSTRAINT: The ONLY valid columns in your response are: '
                       f'{", ".join(_all_cols)}. Any column not in this list is FORBIDDEN '
                       f'— do not use any other column. Multiple sections reuse the same '
                       f'columns; place each section\'s items in ITS specified columns.')
        desc.insert(4, f'There are {len(out_sections)} sections. Your layout_sections '
                       f'response MUST contain ALL of them: {_names}. Each must have '
                       f'at least one row.')
        desc.insert(5, "")

    if fixed:
        desc.append("FIXED CELLS (labels already in the template — return the value only):")
        desc += [f"  {ref} = {lbl}" for ref, lbl in fixed]
        desc.append("")

    seclines = [
        f'      "{slug}": {{ "rows": [\n'
        f'        {{"label_col": "{lcl}", "value_col": "{vcl}", "row": {first_row}, '
        f'"label": "<item name from document>", "value": "<amount>"}}\n'
        f'      ] }}'
        for slug, lcl, vcl, first_row in out_sections
    ]
    fixed_example = ", ".join(f'"{ref}": {{"value": "<amount>", "confidence": "high"}}'
                              for ref, _ in fixed[:4])

    output_format = (
        "Return ONLY valid JSON:\n{\n"
        '  "document_type": "detected type",\n'
        '  "overall_confidence": "high",\n'
        '  "documents": [{\n'
        '    "doc_index": 0,\n'
        '    "layout_sections": {\n' + ",\n".join(seclines) + "\n    },\n"
        '    "extracted_fields": {' + fixed_example + "}\n"
        "  }]\n}\n"
        "RULES:\n"
        "- label_col/value_col are column LETTERS; row is the spreadsheet row NUMBER.\n"
        "- Target a cell by combining them: column letter + row number (e.g. A + 2 = A2).\n"
        "- Extract EVERY line item present in the document — do not stop at the number\n"
        "  of available rows; add as many row objects as the document actually has.\n"
        "- Numbers: strip $ and commas. Dates: YYYY-MM-DD. Missing: \"\".\n"
        "- Put each section's items ONLY into that section's columns."
    )

    si = system_instruction + (
        "\n\nLAYOUT EXTRACTION MODE:\n"
        "The template's line-item rows are intentionally blank. Read the document and "
        "reconstruct each section's line items (name + amount), then place them into "
        "the designated label/value columns. Extract the document's ACTUAL content — "
        "do not invent rows and do not omit any line item."
    )
    doc_text_use = _smart_truncate(doc_text, "table", {})
    user_prompt = (
        "\n".join(desc)
        + "\n=== DOCUMENT TEXT ===\n"
        + (doc_text_use if doc_text_use else "(See document image)")
        + "\n\n=== OUTPUT FORMAT ===\n" + output_format + "\n"
    )
    print(f"[LAYOUT] prompt built: {len(column_groups)} section group(s), "
          f"{len(fixed)} fixed cell(s)", flush=True)
    return si, user_prompt


def _build_vision_prompt(template_data: dict, doc_text: str = "",
                         force_field_mode: bool = False) -> tuple:
    """
    Build extraction prompt split into (system_instruction, user_prompt).

    system_instruction = registry expert persona (stable, doc-type specific).
    user_prompt = template structure + page anchors + self-verification + doc text.

    force_field_mode=True (set by the field-extraction path for labeled/mixed
    templates): honour the routing decision — skip the layout "extract & place"
    short-circuit and the PARALLEL COLUMN GROUPS rule, and build the normal
    field/KV(+table) prompt so Gemini returns extracted_fields, not layout_sections.
    """
    doc_type      = template_data.get("doc_type", "other")
    regions       = template_data.get("regions", {})
    layout        = template_data.get("layout", {})
    primary_mode  = regions.get("primary_mode", "form_kv")
    table_regions = regions.get("table_regions", [])

    # System instruction — expert persona from registry (or unguided when type is unknown)
    if primary_mode == "unguided" and doc_type in ("other", "", None):
        system_instruction = _get_unguided_prompt()
    else:
        system_instruction = _get_system_prompt(doc_type)
    table_rules = _get_table_rules(doc_type)
    if table_rules and primary_mode in ("table", "mixed"):
        system_instruction += f"\n\nTABLE RULES:\n{table_rules}"

    # Bug 5b: inject critical financial accuracy rule when section-context risk is present
    if regions.get("needs_section_context"):
        system_instruction += (
            "\n\nCRITICAL FINANCIAL ACCURACY RULE:\n"
            "This document has MULTIPLE SECTIONS, each with its own subtotal row. "
            "Generic column headers like 'Total' or 'Amount' appear in EVERY section.\n"
            "You MUST match each value to its CORRECT section — do NOT use the wrong "
            "section's total.\n"
            "Rules:\n"
            "1. Read the SECTION HEADER (e.g. 'Current Assets', 'Non-Current Assets', "
            "'Operating Expenses') to identify which section each row belongs to.\n"
            "2. The 'Total Current Assets' row belongs ONLY to the Current Assets section.\n"
            "   Do NOT use that value for 'Total Non-Current Assets' or 'Total Assets'.\n"
            "3. Extract every row in POSITIONAL ORDER — the section header is the "
            "   primary key for resolving ambiguity.\n"
            "4. If you are unsure which section a value belongs to, use the row's "
            "   position in the document as a tiebreaker.\n"
            "FINANCIAL ERROR WARNING: Mixing up section totals (e.g. Total Current "
            "Assets vs Total Assets) is a critical error with legal and financial "
            "consequences. Verify EACH total against its section header before writing it."
        )
        print(f"[BUG5] CRITICAL FINANCIAL ACCURACY RULE injected for {doc_type}", flush=True)

    # Issue 1: inject PARALLEL COLUMN GROUPS RULE when the template has multiple
    # independent label/value column bands on the same row range.
    parallel_groups = regions.get("parallel_column_groups", [])
    if parallel_groups and not force_field_mode:
        group_lines = [
            f"  GROUP {pg['group_id']} \"{pg['section_label']}\": "
            f"labels in column {pg['label_col_letter']}, "
            f"amounts into column {pg['value_col_letter']}"
            for pg in parallel_groups
        ]
        system_instruction += (
            "\n\nPARALLEL COLUMN GROUPS RULE:\n"
            "This template has SIDE-BY-SIDE independent column groups. "
            "Each group occupies the SAME rows but DIFFERENT columns.\n"
            + "\n".join(group_lines) + "\n"
            "CRITICAL RULES:\n"
            "1. Fill ALL groups. Never leave any group empty.\n"
            "2. Each group's amounts go ONLY into that group's designated value column.\n"
            "3. Read the document's LEFT section for GROUP 1 "
            "and RIGHT/NEXT section for GROUP 2.\n"
            "4. Total rows: match EACH total to its OWN group's value column.\n"
            "   'Total Current Assets' → GROUP 1 value column.\n"
            "   'Total Non-Current Assets' → GROUP 2 value column.\n"
            "5. Do NOT copy the same value into multiple groups."
        )
        print(
            f"[PROMPT] PARALLEL COLUMN GROUPS RULE injected "
            f"({len(parallel_groups)} groups)",
            flush=True,
        )

    # ── COMPONENT 6: layout-based extraction trigger ─────────────────────────
    # When the binding map shows table_data cells (column headers but blank,
    # unlabeled line-item rows), switch to the "extract & place" layout prompt.
    # Field-based templates (explicit label→value pairs) keep the logic below.
    binding_map = template_data.get("binding_map")
    if force_field_mode:
        print("[PROMPT] field-mode forced by routing — building field/KV(+table) prompt "
              "(layout short-circuit skipped)", flush=True)
    elif isinstance(binding_map, dict) and binding_map.get("_meta", {}).get("has_table_data"):
        try:
            print("[PROMPT] layout-based extraction selected (table_data present)", flush=True)
            return _build_layout_prompt_parts(binding_map, layout, doc_text, system_instruction)
        except Exception as _lp_e:
            print(f"[LAYOUT] prompt build failed ({exc_brief(_lp_e)}) — using field-based prompt", flush=True)

    # Smart text truncation
    doc_text_use = _smart_truncate(doc_text, primary_mode, regions)

    fields_description      = _build_fields_description(regions, layout)
    extraction_instructions = _build_extraction_instructions(regions, primary_mode, "")
    output_format           = _build_output_format(regions, primary_mode)
    verify_block            = _build_verification_block(primary_mode, table_regions)

    # Build page anchor map — tells AI which page each table lives on
    # Derived purely from scanning the document text for column header names
    # Zero hardcoding — works for any table with any column names
    page_anchor_block = ""
    if table_regions and doc_text and "--- PAGE BREAK ---" in doc_text:
        page_map = _build_page_anchor_map(doc_text, table_regions)
        if page_map:
            anchor_lines = ["=== PAGE LOCATION OF EACH TABLE ==="]
            anchor_lines.append(
                "The document has multiple pages. Each table's data is on a specific page."
            )
            anchor_lines.append(
                "This is determined by where the column headers appear in the text."
            )
            for section, page_num in page_map.items():
                tbl = next((t for t in table_regions
                           if t.get("section_label") == section), None)
                cols = tbl.get("column_names", []) if tbl else []
                col_str = f"({', '.join(cols[:3])})" if cols else ""
                anchor_lines.append(
                    f"  Table \"{section}\" {col_str}: "
                    f"data is on PAGE {page_num} of the document"
                )
            anchor_lines.append(
                "Extract rows for EACH table from its indicated page."
            )
            anchor_lines.append(
                "Do not stop at page 1 if a table is indicated on page 2 or later."
            )
            page_anchor_block = "\n".join(anchor_lines)

    user_prompt = f"""=== EXTRACTION TASK ===

{fields_description}

=== INSTRUCTIONS ===
{extraction_instructions}

{page_anchor_block + chr(10) if page_anchor_block else ""}=== SELF-VERIFICATION (run this before returning) ===
{verify_block}

=== RULES ===
1. MATCH BY MEANING: Labels in the template and the document will differ.
   Match by concept, not exact text.
   Examples: "Rcpt No"="Receipt Number", "Amt"="Amount", "Inv Ref"="Invoice Reference"
   "No of Emp"="Number of Employees", "Fed"="Federal", "YTD"="Year to Date"
   "EIN"="Employer ID Number", "SSN"="Social Security Number"
2. BLANK ROWS IN TEMPLATE are placeholders only — they do NOT limit row count.
   If the document has 15 rows, return 15 rows. If it has 2, return 2.
3. NUMBERS: Return the COMPLETE numeric amount including all digits
   (e.g. "$320.00" -> "320.00" or 320.00). Remove $ £ € ₹ and commas.
   "(2.85)" means -2.85. NEVER return only a currency symbol ($, £, €, etc.)
   as a value — return the AMOUNT, not the sign.
4. DATES: Always YYYY-MM-DD format.
5. MISSING VALUES: Use "" — never "N/A", "null", "not found", or a lone
   currency symbol. A lone currency symbol means the value was not found.
6. ALL PAGES: Extract from every page. Never stop at page 1.
7. HEADERS ARE NOT DATA: Section label rows and column header rows are
   template structure only. Never include them as data rows in table_rows.
8. FIELD SEPARATION RULE: Each cell must contain ONE piece of information
   only. Never combine a company name and address in one cell. Never combine
   a person's name and their contact details in one cell. If a document field
   contains multiple pieces of information, put each piece in its designated
   separate cell.

=== DOCUMENT TEXT ===
{doc_text_use if doc_text_use else "(See document image)"}

=== OUTPUT FORMAT ===
{output_format}
"""
    # Log the output format section so we can verify AI is getting correct instructions
    print(f"[PROMPT] mode={primary_mode} n_tables={len(table_regions)} "
          f"targets={len(regions.get('explicit_targets',[]))} "
          f"kv={len(regions.get('kv_pairs',[]))}", flush=True)
    if table_regions:
        for i, tr in enumerate(table_regions):
            # counts only: section labels and column names are template text
            print(f"[PROMPT] table_{i+1}: "
                  f"{len(tr.get('column_names', []) or [])} column(s) "
                  f"key={'table_'+str(i+1)+'_rows'}", flush=True)
    # The output format is part of the prompt (template text): its size only.
    print(f"[PROMPT] output_format: {len(output_format)} chars (not logged)",
          flush=True)

    return system_instruction, user_prompt


def _build_verification_block(primary_mode: str, table_regions: list) -> str:
    """
    Build a generic self-verification checklist the AI runs before returning.
    No hardcoded numbers, names, or document-specific logic.
    Works for any template structure.
    """
    checks = []

    # Universal checks for all modes
    checks.append(
        "STEP 1 — COUNT CHECK:\n"
        "  Go back to the document text.\n"
        "  Count every data row that exists in EACH table section.\n"
        "  Compare that count to the rows you are about to return.\n"
        "  If your row count is LESS than what the document contains — add the missing rows.\n"
        "  Common mistake: stopping at page 1 when data continues on page 2."
    )

    checks.append(
        "STEP 2 — COMPLETENESS CHECK:\n"
        "  For every table header you identified in the template:\n"
        "    - Did you extract rows for it? If any table has zero rows, that is wrong.\n"
        "    - Scan the document text specifically for that section and add any missing rows.\n"
        "  For every form field marked for extraction:\n"
        "    - Is the value filled? If blank, scan the document again for that label."
    )

    checks.append(
        "STEP 3 — FORMAT CHECK:\n"
        "  For every numeric value you extracted:\n"
        "    - Remove currency symbols ($ £ € ₹) and thousand-separator commas\n"
        "    - Convert accounting negatives: (1,245.00) → -1245.00\n"
        "    - Expand suffixes: 8.41K → 8410, 1.2M → 1200000\n"
        "  For every date value:\n"
        "    - Convert to YYYY-MM-DD\n"
        "    - 'April 30, 2024' → '2024-04-30', '30/04/2024' → '2024-04-30'\n"
        "  For every text value:\n"
        "    - Remove line breaks within a value\n"
        "    - Trim leading/trailing whitespace"
    )

    checks.append(
        "STEP 4 — CROSS-CHECK:\n"
        "  Pick 3 random values you extracted.\n"
        "  Find each one in the document text and confirm it matches exactly.\n"
        "  If any value does not match — correct it before returning."
    )

    if table_regions:
        checks.append(
            "STEP 5 — TABLE INTEGRITY:\n"
            "  For each table, verify:\n"
            "    - Every row has values in ALL columns (no empty columns mid-row)\n"
            "    - No row is a header row, section title, or total/subtotal row\n"
            "    - Rows from different tables are not mixed together\n"
            "    - If a table spans a page break, rows from BOTH pages are included"
        )

    return "\n\n".join(checks)


def _build_fields_description(regions: dict, layout: dict) -> str:
    """
    Build a complete, unambiguous description of the template structure for the AI.
    Handles: multiple tables, two-column layouts, mixed mode, any position.
    """
    lines = []
    primary_mode = regions.get("primary_mode", "form_kv")
    table_regions = regions.get("table_regions", [])
    explicit_targets = regions.get("explicit_targets", [])
    kv_pairs = regions.get("kv_pairs", [])
    two_col_pairs = regions.get("two_col_pairs", [])

    # ── PARALLEL COLUMN GROUPS (takes priority over flat kv_pairs) ───────────────
    parallel_groups = regions.get("parallel_column_groups", [])
    if parallel_groups:
        # Build the target list DIRECTLY from the template grid (not from
        # pg["items"], which can be incomplete when empty value cells aren't
        # stored as grid entries). For each group's column band, list EVERY row
        # that has a label in the label column whose value cell is empty/extract
        # — that is an extraction target. This guarantees Gemini is told exactly
        # which cells to fill instead of guessing.
        grid_cells = layout.get("cells", {})

        def _grid_val(row, col):
            c = grid_cells.get(f"{row},{col}")
            return str(c.get("value") or "").strip() if isinstance(c, dict) else ""

        def _is_target_value_cell(row, col):
            """True when the value cell is empty/missing or explicitly an
            extract target (i.e. NOT a static header like 'Amount')."""
            c = grid_cells.get(f"{row},{col}")
            if not isinstance(c, dict):
                return True                      # not stored → empty → target
            if c.get("extractTarget"):
                return True
            return not str(c.get("value") or "").strip()

        # ── Pass 1: collect every extraction target across all groups, tracking
        #    the SECTION each cell falls under (the nearest header row above it,
        #    i.e. the most recent label whose value cell is a static header). ──
        groups_targets = []   # [(gid, group_label, value_col_letter, [(ref, label, section)])]
        label_counts = {}     # label_text -> occurrences across the whole template
        for pg in parallel_groups:
            gid       = pg["group_id"]
            slbl      = pg["section_label"]
            label_col = pg["label_col"]
            value_col = pg["value_col"]
            v_c       = pg["value_col_letter"]

            label_rows = sorted({
                int(k.split(",")[0])
                for k in grid_cells
                if "," in k
                and k.split(",")[1].isdigit()
                and int(k.split(",")[1]) == label_col
            })

            current_section = slbl
            tgts = []
            for r in label_rows:
                label = _grid_val(r, label_col)
                if not label:
                    continue
                if not _is_target_value_cell(r, value_col):
                    # static header cell (e.g. "Amount") → this row names a section
                    current_section = label
                    continue
                ref = _cell_ref(r, value_col)
                tgts.append((ref, label, current_section))
                label_counts[label] = label_counts.get(label, 0) + 1
            groups_targets.append((gid, slbl, v_c, tgts))

        # ── Pass 2: emit the listing. Ambiguous labels (the same label text used
        #    more than once anywhere in the template) get an inline section hint;
        #    unique labels need none. ──
        lines.append("=== EXTRACTION TARGETS — fill EXACTLY these cells ===")
        lines.append(
            "This template has INDEPENDENT side-by-side column groups. Below is "
            "the COMPLETE list of every cell you must fill, each with the label "
            "that sits next to it. Fill EVERY listed cell."
        )
        lines.append("")

        all_refs = []
        for gid, slbl, v_c, tgts in groups_targets:
            lines.append(f"GROUP {gid} — \"{slbl}\" (Column {v_c}):")
            if tgts:
                for ref, label, section in tgts:
                    hint = (f" (from {section} section)"
                            if label_counts.get(label, 0) > 1 and section else "")
                    lines.append(f"  {ref} = {label}{hint}")
                    all_refs.append(ref)
            else:
                lines.append("  (no extraction targets detected in this group)")
            lines.append("")

        # FIX 1: per-cell matching rule replaces the contradictory per-group
        # "Put ONLY values from the <section> section" footer.
        lines.append(
            "Each cell reference above is mapped to its exact source label. "
            "Extract the value matching that EXACT label from the document. "
            "Do not use section membership to decide — use the label name only. "
            "If a label appears multiple times in the document, use the value "
            "from the row that matches the label text exactly."
        )
        lines.append("")

        # FIX 3: strong, explicit closing directive with a dynamically-generated
        # key list (never hardcoded).
        lines.append(
            "MANDATORY: Your response must contain extracted_fields with EXACTLY "
            f"these keys: [{', '.join(all_refs)}]. "
            "Every key must be present. Use \"\" for any value not found. "
            "Match each key to its label above — ignore section boundaries, use "
            "label text only."
        )
        lines.append("")

    # ── FORM FIELDS ────────────────────────────────────────────────────────────
    elif explicit_targets:
        lines.append("=== FORM FIELDS (marked Extract here) ===")
        lines.append("Fill each cell reference with the matching value from the document.")
        lines.append("Use the cell reference as the key in extracted_fields.")
        for t in explicit_targets:
            lines.append(f"  [{t['ref']}] {t['label']}")
        lines.append("")

    elif kv_pairs and not table_regions:
        lines.append("=== FORM FIELDS (label-value pairs) ===")
        lines.append("Labels are in the left column. Fill the right column.")
        for kv in kv_pairs[:30]:  # limit to avoid token waste
            lines.append(f"  Label: \"{kv['label']}\" -> Fill cell: {kv['value_ref']}")
        lines.append("")

    if two_col_pairs:
        lines.append("=== TWO-COLUMN FORM LAYOUT ===")
        lines.append("This template has label-value pairs on BOTH the left AND right sides of each row.")
        lines.append("Extract BOTH sides. Do NOT treat this as a table.")
        for tc in two_col_pairs[:20]:
            lines.append(f"  LEFT:  [{tc['left_value_ref']}] = \"{tc['left_label']}\"")
            lines.append(f"  RIGHT: [{tc['right_value_ref']}] = \"{tc['right_label']}\"")
        lines.append("")

    # ── TABLES ─────────────────────────────────────────────────────────────────
    # FIX 1: never render table instructions for parallel-group templates,
    # even if table_regions somehow survived region analysis.
    if table_regions and primary_mode != "parallel_groups":
        n = len(table_regions)

        # Group by row to detect same-row tables
        same_row = {}
        for tr in table_regions:
            same_row.setdefault(tr["header_row"], []).append(tr)
        has_same_row = any(len(v) > 1 for v in same_row.values())

        if n == 1:
            lines.append("=== TABLE ===")
        else:
            lines.append(f"=== {n} TABLES ===")
            if has_same_row:
                lines.append(
                    "IMPORTANT: Some tables appear SIDE BY SIDE on the same row.\n"
                    "They are separated by empty columns. Use the column range to\n"
                    "identify which data belongs to which table."
                )
            lines.append("")

        # Bug 5c: detect generic column headers that repeat across sections
        needs_section_ctx = regions.get("needs_section_context", False)

        for i, tr in enumerate(table_regions):
            section   = tr.get("section_label", f"Table {i+1}")
            col_start = chr(ord('A') + tr.get("start_col", 0))
            col_end   = chr(ord('A') + min(tr.get("end_col", 0), 25))
            col_range = f"columns {col_start} to {col_end}"

            lines.append(f"TABLE {i+1}: \"{section}\"")
            lines.append(f"  Position: row {tr['header_row']+1}, {col_range}")
            lines.append(f"  Columns:  {', '.join(tr['column_names'])}")
            lines.append(
                f"  Extract:  ALL data rows for this table from the document.\n"
                f"            There is NO row limit — blank rows in the template\n"
                f"            are just placeholders. Extract every row that exists."
            )
            if tr.get("col_range") and n > 1:
                lines.append(
                    f"  NOTE: Data for this table is in {col_range} of the document.\n"
                    f"        Do not mix it with data from other tables."
                )
            if needs_section_ctx:
                lines.append(
                    f"  SECTION ACCURACY: This table has generic column names. "
                    f"Each row belongs to a specific SECTION of the document "
                    f"(identified by a section header above it). "
                    f"Match every value to its CORRECT section — positional order matters."
                )
            lines.append("")

    if not lines:
        plain_text_desc = regions.get("plain_text_description", "")
        if plain_text_desc:
            # Bug 4 + Bug 1: template has plain-text description only
            lines.append("=== UNGUIDED EXTRACTION (template description provided) ===")
            lines.append(f"Template description: {plain_text_desc}")
            lines.append("Extract all fields relevant to this document based on the description above.")
        elif primary_mode == "unguided":
            lines.append("=== UNGUIDED EXTRACTION ===")
            lines.append("No template structure was detected. Extract all fields from the document.")
        else:
            lines.append("=== AUTO-EXTRACT MODE ===")
            lines.append("The template has labelled fields. Match each label to its value in the document.")
            lines.append("Use cell references as keys.")

    # ── TRANSPOSED TABLES ──────────────────────────────────────────────────────
    transposed = regions.get("transposed_tables", [])
    # FIX 1: never render transposed-table instructions for parallel-group templates.
    if transposed and primary_mode != "parallel_groups":
        lines.append("=== TRANSPOSED TABLE (horizontal layout) ===")
        lines.append("This template has a HORIZONTAL table where:")
        lines.append("  - Row LABELS are in the leftmost column (column A)")
        lines.append("  - Each subsequent column contains one complete record")
        lines.append("  - Extract each column as a separate record/row")
        lines.append("")
        for tt in transposed:
            lines.append(f"  Row labels: {', '.join(tt['row_names'][:6])}")
            lines.append(f"  Data columns: {len(tt['data_cols'])} records")
            lines.append("  Return each column as one object in table_rows")
        lines.append("")

    return "\n".join(lines)


def _build_extraction_instructions(regions: dict, primary_mode: str,
                                    table_rules: str) -> str:
    """Build extraction instructions covering all known failure scenarios."""
    instructions = []
    table_regions = regions.get("table_regions", [])
    n_tables = len(table_regions)

    # ── UNIVERSAL RULES (always included) ─────────────────────────────────────
    instructions.append("""=== UNIVERSAL EXTRACTION RULES ===
1. MATCH BY MEANING: Template labels and document labels will differ.
   Match by concept, not exact text.
   "Rcpt No" = "Receipt Number", "Amt Rcvd" = "Amount Received",
   "Inv Ref" = "Invoice Reference", "Pmt Mthd" = "Payment Method".
   An abbreviation in the template refers to the full label in the document.

2. SECTION HEADERS ARE NOT DATA: Cells like "Bank Information", "Payment Details",
   "Earning Table", "Deduction Table" are visual section organizers.
   NEVER extract a section header text as a field value.

3. MULTI-PAGE DOCUMENTS: The document may span 2 or more pages.
   Extract data from ALL pages. Tables may continue across page breaks.
   A row on page 2 is just as valid as a row on page 1.
   Do NOT stop extracting at the end of page 1.

4. NUMBERS: Strip all currency symbols ($, £, €, ₹) and commas.
   Negative values: "(2.85)" means -2.85. "8.41K" means 8410.
   Page-break splits: if "7,513.0" appears on page 1 and "3" on page 2,
   the correct value is 7513.03 — combine them.

5. DATES: Always YYYY-MM-DD. "Feb 10, 2024" -> "2024-02-10".

6. EMPTY CELLS: If a field has no corresponding value, use "".
   Never invent values. Never copy a label as a value.

7. CELL REFERENCES: Use the exact cell reference from the template (B3, D10, etc.)
   as the key in extracted_fields. The label is for your understanding only.

8. FORMULA CELLS: If the template shows =SUM(...), calculate and return the number.""")

    # ── MODE-SPECIFIC INSTRUCTIONS ─────────────────────────────────────────────
    if primary_mode == "parallel_groups":
        parallel_groups = regions.get("parallel_column_groups", [])
        gmap = "\n".join(
            f'  GROUP {pg["group_id"]} "{pg["section_label"]}": '
            f'value column = {pg["value_col_letter"]}'
            for pg in parallel_groups
        )
        instructions.append(
            "=== PARALLEL COLUMN GROUP EXTRACTION ===\n"
            "This template has multiple INDEPENDENT column groups side by side.\n"
            "You MUST extract values for EVERY group listed below.\n\n"
            + gmap + "\n\n"
            "RULES:\n"
            "1. Scan the document for EACH group's section independently.\n"
            "2. Put each group's amounts into its designated value column ONLY.\n"
            "3. Zero filled cells in any group = extraction failure.\n"
            "4. Match totals to their group:\n"
            "   'Total Current Assets' → GROUP 1 value column.\n"
            "   'Total Non-Current Assets' → GROUP 2 value column.\n"
            "5. If the document has content in two side-by-side columns, "
            "read BOTH columns independently."
        )

    elif primary_mode == "unguided":
        # Bug 1: no regions found — use doc_type persona only
        instructions.append(
            "=== UNGUIDED EXTRACTION ===\n"
            "No template layout could be parsed for this document. "
            "Extract ALL fields and values present in the document based on "
            "your domain expertise for this document type.\n"
            "Return every label-value pair you can identify. "
            "Use the label text as the key in extracted_fields.\n"
            "For any tables, extract all rows into table_rows."
        )

    elif primary_mode in ("form_with_targets", "form_kv"):
        instructions.append("""=== FORM EXTRACTION ===
Fill each marked field with exactly ONE value from the document.
Blank rows between sections are visual spacers — skip them.
Merged header cells are section titles — do not extract their text as values.
If a field appears in both a section header and as a real value,
extract the real value (the data, not the heading).""")

    elif primary_mode == "table":
        instructions.append("""=== TABLE EXTRACTION ===
Extract EVERY data row from the document table.
The table may start anywhere on the page — find the column headers.
Skip: the header row itself, subtotal rows, total rows, blank rows.
Include ALL data rows including those on page 2.""")
        if table_rules:
            instructions.append(f"Document-specific rules:\n{table_rules}")

    elif primary_mode == "mixed":
        if n_tables == 1:
            instructions.append("""=== MIXED MODE: FORM FIELDS + TABLE ===
PART 1 - FORM FIELDS: Fill each labelled extraction cell with its value.
PART 2 - TABLE: Extract every data row from the table section.
Both parts are equally important. Do not skip either.""")
        else:
            # Bug 3: multiple tables — use SEPARATE array keys matching _build_output_format
            # The old code used a single table_rows array + "Table" field, which
            # contradicted the output format and caused AI to misroute rows.
            table_key_map = []
            for i, tr in enumerate(table_regions):
                name  = tr.get("section_label", f"Table {i+1}")
                key   = re.sub(r'[^a-z0-9]', '_', name.lower()).strip('_') + "_rows"
                col_s = chr(ord('A') + tr.get("start_col", 0))
                col_e = chr(ord('A') + min(tr.get("end_col", 0), 25))
                cols  = ", ".join(tr.get("column_names", []))
                table_key_map.append(
                    f'  JSON key "{key}" → table "{name}" '
                    f'(columns: {cols}, template cols {col_s}–{col_e})'
                )
            instructions.append(
                f"=== MIXED MODE: FORM FIELDS + {n_tables} SEPARATE TABLES ===\n"
                f"PART 1 - FORM FIELDS: Fill each labelled extraction cell.\n"
                f"PART 2 - {n_tables} TABLES: Each table gets its OWN JSON array key.\n\n"
                f"CRITICAL — use these EXACT JSON array key names:\n"
                + "\n".join(table_key_map) + "\n\n"
                f"RULES:\n"
                f"- DO NOT use a single 'table_rows' key — use the separate keys above\n"
                f"- Each row goes into its table's OWN array key only\n"
                f"- Extract EVERY row from EVERY table — zero rows from any table is WRONG\n"
                f"- Blank rows in the template are placeholders, not row limits\n"
                f"- See PAGE LOCATION section for which page each table is on\n"
                f"- Do NOT include column header rows as data rows"
            )
        if table_rules:
            instructions.append(f"Document-specific rules:\n{table_rules}")

    # ── TWO-COLUMN REMINDER ────────────────────────────────────────────────────
    if regions.get("two_col_pairs"):
        instructions.append("""=== TWO-COLUMN LAYOUT REMINDER ===
Extract BOTH left-side and right-side values on each row.
This is a form, not a table. Each row has 2 label-value pairs.
Left label and right label are independent fields.""")

    return "\n\n".join(instructions)


def _build_output_format(regions: dict, primary_mode: str) -> str:
    """
    Build the JSON output format specification.
    Handles: single table, multiple tables, form only, mixed mode.
    """
    table_regions = regions.get("table_regions", [])
    n_tables = len(table_regions)

    # Build example extracted_fields
    field_example = '"B3": {"value": "extracted value", "confidence": "high"}'

    # Build table examples
    def table_example(tr):
        cols = tr.get("column_names", ["Col1", "Col2"])[:4]
        return "{" + ", ".join(f'"{c}": "value"' for c in cols) + "}"

    if primary_mode == "unguided":
        # Bug 1: no template regions — generic free-form output
        return f"""Return ONLY valid JSON:
{{
  "document_type": "detected type",
  "overall_confidence": "medium",
  "document_count": 1,
  "documents": [{{
    "doc_index": 0,
    "doc_hint": "brief description",
    "extracted_fields": {{
      "Field Name 1": {{"value": "extracted value", "confidence": "high"}},
      "Field Name 2": {{"value": "extracted value", "confidence": "medium"}}
    }},
    "table_rows": [],
    "notes": ""
  }}]
}}
RULES:
- extracted_fields keys = the label/field name from the document
- Include every field you can identify
- Numbers: no $ or commas. Dates: YYYY-MM-DD."""

    elif primary_mode == "table" and n_tables == 1:
        ex = table_example(table_regions[0])
        return f"""Return ONLY valid JSON:
{{
  "document_type": "detected type",
  "overall_confidence": "high",
  "document_count": 1,
  "documents": [{{
    "doc_index": 0,
    "doc_hint": "brief description",
    "table_rows": [{ex}, {ex}],
    "row_count": 2,
    "notes": ""
  }}]
}}
RULES: table_rows = one object per data row. Skip headers, totals, blank rows. Numbers: no $ or commas."""

    elif primary_mode == "mixed" and n_tables == 1:
        ex = table_example(table_regions[0])
        return f"""Return ONLY valid JSON:
{{
  "document_type": "detected type",
  "overall_confidence": "high",
  "document_count": 1,
  "documents": [{{
    "doc_index": 0,
    "doc_hint": "brief description",
    "extracted_fields": {{{field_example}}},
    "table_rows": [{ex}],
    "row_count": 1,
    "notes": ""
  }}]
}}
RULES:
- extracted_fields: cell refs as keys (B3, D10), one value per field
- table_rows: one object per data row, using exact column names
- Numbers: no $ or commas. Dates: YYYY-MM-DD."""

    elif primary_mode == "mixed" and n_tables > 1:
        # Multiple tables — use ONE table_rows array with a "Table" column
        # Show a SEPARATE example row for each table with its OWN columns
        # This prevents the AI from merging columns across tables
        # Build separate array key and example for each table
        # Using SEPARATE arrays per table is the ONLY reliable way to prevent
        # the AI from merging columns across tables into one row structure
        table_blocks = []
        table_keys   = []
        for tr in table_regions:
            name    = tr.get("section_label", "")
            cols    = tr.get("column_names", [])
            col_s   = chr(ord('A') + tr.get("start_col", 0))
            col_e   = chr(ord('A') + min(tr.get("end_col", 0), 25))
            # Make a safe JSON key from section label
            key     = re.sub(r'[^a-z0-9]', '_', name.lower()).strip('_') + "_rows"
            table_keys.append(key)
            ex_row  = {c: "value" for c in cols}
            table_blocks.append(
                f'    "{key}": [\n'
                f'      {json.dumps(ex_row)}\n'
                f'    ]  /* ALL rows from "{name}" table (cols {col_s}-{col_e}) */'
            )

        blocks_str = ",\n".join(table_blocks)

        table_rules_str = []
        for i, (tr, key) in enumerate(zip(table_regions, table_keys)):
            name = tr.get("section_label", f"Table {i+1}")
            cols = ", ".join(tr.get("column_names", []))
            col_s = chr(ord('A') + tr.get("start_col", 0))
            col_e = chr(ord('A') + min(tr.get("end_col", 0), 25))
            table_rules_str.append(
                f'  "{key}": rows from "{name}" section '
                f'(columns: {cols}, template cols {col_s}-{col_e})'
            )

        return f"""Return ONLY valid JSON:
{{
  "document_type": "detected type",
  "overall_confidence": "high",
  "document_count": 1,
  "documents": [{{
    "doc_index": 0,
    "doc_hint": "brief description",
    "extracted_fields": {{{field_example}}},
{blocks_str},
    "notes": ""
  }}]
}}
RULES FOR {len(table_regions)} SEPARATE TABLES:
Each table gets its OWN array key. Do NOT use a single "table_rows" array.
Do NOT merge columns from different tables into the same row.

{chr(10).join(table_rules_str)}

For each table array:
- Extract ALL data rows from that table section in the document
- Include rows from ALL pages (document may continue on page 2+)
- Each row uses ONLY that table's columns — do not add columns from other tables
- Blank rows in the template are placeholders, not row limits
- Numbers: no $ or commas. Dates: YYYY-MM-DD
- Do NOT include header rows or section title rows as data rows"""

    else:
        # Form only
        return f"""Return ONLY valid JSON:
{{
  "document_type": "detected type",
  "overall_confidence": "high",
  "document_count": 1,
  "documents": [{{
    "doc_index": 0,
    "doc_hint": "brief description",
    "extracted_fields": {{
      {field_example},
      "D3": {{"value": "another value", "confidence": "high"}}
    }},
    "notes": ""
  }}]
}}
RULES:
- extracted_fields keys MUST be cell references (B3, D10, etc.)
- Include every marked field, even if value is ""
- Numbers: no $ or commas. Dates: YYYY-MM-DD."""
