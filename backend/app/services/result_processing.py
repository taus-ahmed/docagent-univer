"""pdfplumber validation, value normalisation and the vision result processors.

Moved verbatim from app/api/routes/extract.py (round 13); extract.py re-exports every name.
"""

import app.services.paths  # noqa: F401  (engine on sys.path)
from app.models import DocumentResult
from app.services.template_parsing import _cell_ref
from app.services.template_parsing import _get_numeric_fields
from log_safety import doc_ref
from log_safety import exc_brief
import re
# --imports-end--


def _validate_with_pdfplumber(extracted_fields: dict, doc_text: str,
                               table_rows: list = None) -> dict:
    """
    Cross-check AI-extracted values against pdfplumber text.

    For each extracted value:
      - Search for it (or a close match) in the pdfplumber text
      - If found: keep confidence as-is or upgrade to high
      - If not found: downgrade confidence to low, flag for review

    This is the safety net against AI hallucinations.
    A value the AI invented will not appear anywhere in the pdfplumber text.
    A value the AI correctly extracted will appear in the text.
    """
    if not doc_text:
        return {"validated": extracted_fields, "flagged": [], "confidence_map": {}}

    doc_text_lower = doc_text.lower()
    validated = {}
    flagged = []
    confidence_map = {}

    for ref, field_data in extracted_fields.items():
        if isinstance(field_data, dict):
            value = str(field_data.get("value", "")).strip()
        else:
            value = str(field_data).strip()

        if not value or value == "":
            validated[ref] = {"value": "", "confidence": "high", "validated": True}
            continue

        # Check if value appears in pdfplumber text
        found = _check_value_in_text(value, doc_text_lower)

        if found:
            # Confirmed - upgrade to high confidence
            final_confidence = "high"
            validated[ref] = {"value": value, "confidence": final_confidence,
                               "validated": True, "pdfplumber_confirmed": True}
        else:
            # Not found - this might be hallucinated or normalised
            # Check if a variant of the value appears (e.g. normalised date)
            variant_found = _check_value_variants(value, doc_text)

            if variant_found:
                final_confidence = "medium"
                validated[ref] = {"value": value, "confidence": final_confidence,
                                   "validated": True, "pdfplumber_confirmed": "variant"}
            else:
                # Value not found at all - flag for review
                final_confidence = "low"
                validated[ref] = {"value": value, "confidence": final_confidence,
                                   "validated": False, "pdfplumber_confirmed": False,
                                   "needs_review": True}
                flagged.append({"ref": ref, "value": value, "reason": "not found in document text"})

        confidence_map[ref] = final_confidence

    # Validate table rows
    validated_rows = []
    if table_rows:
        for row in table_rows:
            validated_row = {}
            for col, val in row.items():
                val_str = str(val).strip()
                if not val_str:
                    validated_row[col] = {"value": "", "confidence": "high"}
                    continue
                found = _check_value_in_text(val_str, doc_text_lower)
                if found:
                    validated_row[col] = {"value": val_str, "confidence": "high"}
                else:
                    variant = _check_value_variants(val_str, doc_text)
                    validated_row[col] = {
                        "value": val_str,
                        "confidence": "medium" if variant else "low",
                    }
            validated_rows.append(validated_row)

    return {
        "validated_fields": validated,
        "validated_rows": validated_rows,
        "flagged": flagged,
        "confidence_map": confidence_map,
        "flag_count": len(flagged),
    }


def _check_value_in_text(value: str, doc_text_lower: str) -> bool:
    """Check if a value appears in the document text."""
    if not value or len(value) < 2:
        return True  # Short values - don't flag

    val_lower = value.lower().strip()

    # Direct match
    if val_lower in doc_text_lower:
        return True

    # Numeric match - strip formatting
    val_numeric = re.sub(r'[^0-9.]', '', value)
    if len(val_numeric) >= 4:
        doc_numeric = re.sub(r'[^0-9.]', '', doc_text_lower)
        if val_numeric in doc_numeric:
            return True

    return False


def _check_value_variants(value: str, doc_text: str) -> bool:
    """
    Check if any variant of the value appears in the document.
    Handles date normalisation, number formatting etc.
    """
    # Date variants: "2024-01-31" -> check for "January 31", "31/01", "01/31" etc.
    date_match = re.match(r'(\d{4})-(\d{2})-(\d{2})', value)
    if date_match:
        y, m, d = date_match.groups()
        month_names = ["january","february","march","april","may","june",
                       "july","august","september","october","november","december"]
        month_name = month_names[int(m) - 1]
        variants = [
            f"{d}/{m}/{y}", f"{m}/{d}/{y}", f"{d}-{m}-{y}",
            f"{month_name} {int(d)}", f"{int(d)} {month_name}",
            f"{month_name[:3]} {int(d)}", f"{int(d)} {month_name[:3]}",
        ]
        doc_lower = doc_text.lower()
        return any(v in doc_lower for v in variants)

    # Amount variants: "8410.00" -> check for "$8,410", "8,410.00" etc.
    amount_match = re.match(r'^(\d+)\.(\d{2})$', value)
    if amount_match:
        integer_part = amount_match.group(1)
        # Check for the integer part at least
        if len(integer_part) >= 4 and integer_part in doc_text.replace(",", ""):
            return True

    return False


def _clean_cell(val) -> str:
    if val is None: return ""
    return " ".join(str(val).strip().split())


def _find_header_row(table, col_names):
    col_lower = [c.lower() for c in col_names]
    best_idx, best_score = None, 0
    for i, row in enumerate(table[:8]):
        if not row: continue
        row_vals = [_clean_cell(c).lower() for c in row]
        score = sum(1 for col in col_lower if any(col in cell or cell in col for cell in row_vals if cell))
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx if best_score >= max(1, len(col_names) // 2) else None


def _match_columns(col_names, pdf_headers):
    import difflib
    mapping = {}
    pdf_lower = [h.lower() for h in pdf_headers]
    for col in col_names:
        cl = col.lower()
        if cl in pdf_lower:
            mapping[col] = pdf_lower.index(cl); continue
        for i, h in enumerate(pdf_lower):
            if cl in h or h in cl:
                mapping[col] = i; break
        else:
            matches = difflib.get_close_matches(cl, pdf_lower, n=1, cutoff=0.6)
            if matches:
                mapping[col] = pdf_lower.index(matches[0])
    return mapping


def _normalise_values(row: dict, doc_type: str) -> dict:
    numeric_fields = _get_numeric_fields(doc_type)
    cleaned = {}
    for k, v in row.items():
        if v is None:
            cleaned[k] = ""; continue
        s = str(v).strip()
        kl = k.lower().replace(" ", "_")
        if any(kl == f or kl.endswith(f) for f in numeric_fields):
            s = re.sub(r'[£€$¥₹,\s]', '', s)
            s = re.sub(r'^\((.+)\)$', r'-\1', s)
        cleaned[k] = s
    return cleaned


def _normalize_value(v) -> str:
    """
    Normalize a single extracted value:
    - Numbers: strip $£€₹ and commas, convert (x) to -x, expand K/M
    - Dates: normalize to YYYY-MM-DD
    - Empty/null: return ""
    """
    if v is None:
        return ""
    s = str(v).strip()
    if not s or s.lower() in ("null", "n/a", "none", "not found", "–", "-"):
        return ""

    # Negative accounting format: (2.85) -> -2.85
    m = re.match(r'^\(([0-9,]+\.?[0-9]*)\)$', s)
    if m:
        return "-" + m.group(1).replace(",", "")

    # Month name date formats
    months = {"jan":1,"feb":2,"mar":3,"apr":4,"may":5,"jun":6,
              "jul":7,"aug":8,"sep":9,"oct":10,"nov":11,"dec":12}
    m_name = re.match(
        r'^(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})$|^([A-Za-z]{3,9})[. ]+(\d{1,2}),?\s+(\d{4})$', s)
    if m_name:
        try:
            if m_name.group(1):
                d, mo, y = int(m_name.group(1)), months.get(m_name.group(2).lower()[:3]), int(m_name.group(3))
            else:
                mo = months.get(m_name.group(4).lower()[:3])
                d, y = int(m_name.group(5)), int(m_name.group(6))
            if mo:
                return f"{y}-{mo:02d}-{d:02d}"
        except Exception:
            pass

    # Numeric date formats
    date_patterns = [
        (r'^(\d{1,2})/(\d{1,2})/(\d{4})$',  lambda m: f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"),
        (r'^(\d{1,2})-(\d{1,2})-(\d{4})$',  lambda m: f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"),
    ]
    for pattern, formatter in date_patterns:
        m = re.match(pattern, s)
        if m:
            try:
                return formatter(m)
            except Exception:
                pass

    # Currency/number cleanup. Strip currency symbols from the START only (a lone
    # symbol must never replace a real value, and digits must never be lost).
    _CURRENCY = "$£€₹¥"
    stripped = s
    had_currency = False
    while stripped and stripped[0] in _CURRENCY:
        stripped = stripped[1:].lstrip()
        had_currency = True
    num_candidate = stripped.replace(",", "").strip()

    # K / M suffix expansion (e.g. "5K" -> 5000, "1.2M" -> 1200000)
    km = re.match(r'^(-?[0-9.]+)[Kk]$', num_candidate)
    if km:
        try:
            return str(float(km.group(1)) * 1000)
        except Exception:
            pass
    mm = re.match(r'^(-?[0-9.]+)[Mm][Mm]?$', num_candidate)
    if mm:
        try:
            return str(float(mm.group(1)) * 1_000_000)
        except Exception:
            pass

    # A valid number after stripping the leading currency -> return it as a number,
    # but only for clearly-monetary values (had a currency symbol, a thousands
    # comma, or a decimal point). A bare integer is left as a string so IDs /
    # invoice numbers / leading zeros are never mangled.
    if (re.match(r'^-?[0-9]+\.?[0-9]*$', num_candidate)
            and (had_currency or "," in s or "." in num_candidate)):
        try:
            return float(num_candidate)
        except Exception:
            pass

    # Stripping a currency symbol left nothing usable (e.g. value was just "$"):
    # return the original unchanged — never lose data, never blank it silently.
    if had_currency and not num_candidate:
        return s

    return s


def _normalize_field_values(fields: dict) -> dict:
    """Normalize all values in an extracted_fields dict."""
    if not fields:
        return fields
    result = {}
    for k, v in fields.items():
        if isinstance(v, dict):
            val = v.get("value", "")
            result[k] = {**v, "value": _normalize_value(val)}
        else:
            result[k] = _normalize_value(v)
    return result


def _normalize_row_values(row: dict) -> dict:
    """Normalize all values in a table row."""
    if not row:
        return row
    return {k: _normalize_value(v) for k, v in row.items()}


def _fix_split_decimals(fields: dict) -> dict:
    """
    Fix numeric values split across page breaks.
    e.g. {"Net Pay": "7513.0", "unknown_1": "3"} -> {"Net Pay": "7513.03"}
    Pattern: a value ending in ".<digit>" or ".<digit>0" followed by a lone
    1-2 digit orphan value that completes the decimal.
    """
    if not fields:
        return fields
    result = {}
    items = list(fields.items())
    skip_next = False
    for i, (key, val) in enumerate(items):
        if skip_next:
            skip_next = False
            continue
        val_str = str(val).strip() if val is not None else ""
        # Check if this value looks like a truncated decimal: ends with "."
        # or has fewer decimal digits than expected (e.g. "7513.0" when full is "7513.03")
        if i + 1 < len(items):
            next_key, next_val = items[i + 1]
            next_str = str(next_val).strip() if next_val is not None else ""
            # If next value is a lone 1-2 digit number and current ends with decimal
            if (re.match(r'^\d{1,2}$', next_str) and
                re.match(r'^\d[\d,]*\.\d{0,2}$', val_str.replace(',', ''))):
                # Combine: "7513.0" + "3" = "7513.03"
                clean = val_str.replace(',', '')
                if clean.endswith('.'):
                    merged = clean + next_str
                elif len(clean.split('.')[-1]) < 2:
                    merged = clean + next_str
                else:
                    merged = val_str
                    result[key] = val
                    continue
                try:
                    result[key] = float(merged)
                    skip_next = True
                    continue
                except ValueError:
                    pass
        result[key] = val
    return result


def _fix_split_decimals_row(row: dict) -> dict:
    """Apply decimal split fix to a single table row."""
    return _fix_split_decimals(row) if row else row


def _validate_row_alignment(
    table_rows: list, table_regions: list
) -> tuple:
    """
    Bug 6: Check that all columns in each table have consistent row presence.
    When the AI returns rows where some columns are systematically absent for
    the first N rows, the data is misaligned (column 2 started at row 13 instead of 1).

    Returns (rows, is_misaligned, warning_msg).
    If misalignment is detected, attempt re-alignment by removing leading empty rows.
    """
    if not table_rows or not table_regions:
        return table_rows, False, ""

    # Collect expected columns per table_source
    expected_cols: dict = {}
    for tr in table_regions:
        name = tr.get("section_label", "")
        key = re.sub(r'[^a-z0-9]', '_', name.lower()).strip('_')
        expected_cols[key] = tr.get("column_names", [])
    # Also accept "table_rows" as the default source
    if table_regions:
        expected_cols["table"] = table_regions[0].get("column_names", [])

    # Group rows by _table_source (or use the single table case)
    groups: dict = {}
    for row in table_rows:
        src = row.get("_table_source", "table")
        groups.setdefault(src, []).append(row)

    warnings = []
    final_rows = []
    is_misaligned = False

    for src, rows in groups.items():
        cols = expected_cols.get(src, [])
        if not cols or len(rows) < 3:
            final_rows.extend(rows)
            continue

        # For each expected column, count how many rows have a non-empty value
        col_fill = {}
        for col in cols:
            col_fill[col] = sum(1 for r in rows if r.get(col, "") not in ("", None))

        if not col_fill:
            final_rows.extend(rows)
            continue

        max_fill = max(col_fill.values())
        min_fill = min(col_fill.values())

        # If the fill counts differ by more than 25% across columns → misalignment
        if max_fill > 0 and (max_fill - min_fill) / max_fill > 0.25:
            is_misaligned = True
            # Find columns with low fill
            sparse_cols = [c for c, f in col_fill.items() if f < max_fill * 0.75]
            warn = (
                f"[BUG6] Row-column misalignment in source='{src}': "
                f"max_fill={max_fill}, min_fill={min_fill}, "
                f"sparse_cols={sparse_cols} — flagging for review"
            )
            print(warn, flush=True)
            warnings.append(warn)
            # Attempt repair: strip leading rows that are empty in ALL sparse columns
            repaired = []
            leading_empty_stripped = 0
            for row in rows:
                if not repaired and all(
                    row.get(c, "") in ("", None) for c in sparse_cols
                ):
                    leading_empty_stripped += 1
                    continue
                repaired.append(row)
            if repaired and leading_empty_stripped > 0:
                print(
                    f"[BUG6] Stripped {leading_empty_stripped} leading-empty rows "
                    f"to repair alignment for '{src}'",
                    flush=True,
                )
                final_rows.extend(repaired)
            else:
                final_rows.extend(rows)
        else:
            final_rows.extend(rows)

    return final_rows, is_misaligned, "; ".join(warnings)


def _regions_to_jsonable(regions: dict) -> dict:
    """FIX 4: make the regions dict JSON-serializable so it can be persisted in
    document_results.extraction_json and reused verbatim at export time."""
    out = dict(regions or {})
    slr = out.get("section_label_rows")
    if isinstance(slr, (set, frozenset)):
        out["section_label_rows"] = sorted(slr)
    return out


def _coerce_extracted_fields(raw_doc: dict, regions: dict) -> tuple:
    """
    FIX 3: enforce the extracted_fields (cell-ref keyed) schema on the AI response
    for form / parallel-group templates.

    Returns (extracted_fields_dict, warning_str). warning_str is non-empty when the
    response had to be remapped/flattened or could not be reconciled — the caller
    uses it to flag the document for review instead of silently writing nothing.
    """
    import re as _re
    primary_mode = regions.get("primary_mode", "form_kv")
    ef = raw_doc.get("extracted_fields", {})
    ref_re = _re.compile(r'^[A-Z]+[0-9]+$')

    form_modes = ("parallel_groups", "form_kv", "form_with_targets", "mixed")
    if primary_mode not in form_modes:
        return (ef if isinstance(ef, dict) else {}), ""

    # Ordered (ref, label) bindings exactly as presented to the AI in the prompt.
    ordered = []
    for pg in regions.get("parallel_column_groups", []):
        for it in pg.get("items", []):
            if it.get("value_ref"):
                ordered.append((it["value_ref"], (it.get("label") or "")))
    for kv in regions.get("kv_pairs", []):
        if kv.get("value_ref"):
            ordered.append((kv["value_ref"], (kv.get("label") or "")))
    for t in regions.get("explicit_targets", []):
        if t.get("ref"):
            ordered.append((t["ref"], (t.get("label") or "")))
    label_to_ref = {(lbl or "").strip().lower(): ref
                    for ref, lbl in ordered if (lbl or "").strip()}

    # Case 1: already a cell-ref-keyed dict → accept as-is.
    if isinstance(ef, dict) and ef:
        ref_keys = [k for k in ef if ref_re.match(str(k))]
        if len(ref_keys) >= max(1, len(ef) // 2):
            return ef, ""
        # Case 2: label-keyed dict → remap labels back to cell refs.
        remapped = {}
        for k, v in ef.items():
            if ref_re.match(str(k)):
                remapped[str(k)] = v
            else:
                ref = label_to_ref.get(str(k).strip().lower())
                if ref:
                    remapped[ref] = v
        if remapped:
            return remapped, (f"AI returned label-keyed fields; remapped "
                              f"{len(remapped)} to cell refs (verify)")

    # Case 3: no usable extracted_fields but table_rows present → flatten by label match.
    table_rows = list(raw_doc.get("table_rows", []) or [])
    for key, val in raw_doc.items():
        if key.endswith("_rows") and key != "table_rows" and isinstance(val, list):
            table_rows.extend(val)
    if table_rows and ordered:
        _num_re = _re.compile(r'^[\$\-\(\)]?[\d,]+(?:\.\d+)?\)?$')
        flat = {}
        for row in table_rows:
            if not isinstance(row, dict):
                continue
            row_label, row_value = "", ""
            for k, v in row.items():
                if str(k).startswith("_"):
                    continue
                sv = str(v).strip()
                if not sv:
                    continue
                if any(ch.isalpha() for ch in sv) and not row_label:
                    row_label = sv
                elif _num_re.match(sv.replace(" ", "")) and not row_value:
                    row_value = sv
            if not row_label:
                continue
            ref = label_to_ref.get(row_label.strip().lower())
            if not ref:
                rl = row_label.strip().lower()
                for lbl, r in label_to_ref.items():
                    if lbl and (lbl in rl or rl in lbl):
                        ref = r
                        break
            if ref and row_value:
                flat[ref] = {"value": row_value, "confidence": "medium"}
        if flat:
            return flat, (f"AI returned table_rows instead of extracted_fields; "
                          f"flattened {len(flat)} values to cell refs (verify)")

    # Case 4: cannot reconcile → keep whatever we had, flag for review.
    if isinstance(ef, dict) and ef:
        return ef, ""
    return {}, ("AI response had no usable extracted_fields for a form/parallel "
                "template — flagged for review")


def _process_vision_result(raw_doc: dict, template_data: dict, filename: str,
                            doc_type: str, elapsed: float, extraction,
                            doc_text: str, seg_hint: str = "",
                            doc_index: int = 0) -> object:
    """
    Process the result from a single document extracted by vision.
    Applies pdfplumber validation to every extracted value.
    """
    from orchestrator import DocumentExtractionResult

    # Unwrap the documents[] wrapper if Gemini nested the result inside it.
    # Some call sites pass extraction.parsed_json directly (e.g. the image path),
    # so the document fields (layout_sections, extracted_fields, table_rows) end up
    # nested under documents[0] instead of at the top level — which silently lost
    # layout_sections and extracted_fields. Idempotent for callers that already
    # unwrapped (documents[0] has no "documents" key).
    if (isinstance(raw_doc, dict) and isinstance(raw_doc.get("documents"), list)
            and raw_doc["documents"] and isinstance(raw_doc["documents"][0], dict)):
        raw_doc = raw_doc["documents"][0]

    regions = template_data.get("regions", {})
    layout = template_data.get("layout", {})
    cells = layout.get("cells", {})
    primary_mode = regions.get("primary_mode", "form_kv")

    # FIX 3: coerce/validate the AI response into the cell-ref extracted_fields
    # schema the writer expects; _schema_warn is set when reconciliation was needed.
    extracted_fields_raw, _schema_warn = _coerce_extracted_fields(raw_doc, regions)
    confidence_raw = raw_doc.get("confidence", "medium")
    if isinstance(confidence_raw, dict):
        confidence_raw = "medium"

    # -- Collect table rows from ALL tables in response ------------------------
    # For single-table responses: raw_doc["table_rows"]
    # For multi-table responses: raw_doc["earning_table_rows"], raw_doc["deduction_table_rows"] etc.
    # We collect all into a single list, adding a "table_source" key to each row
    table_rows_raw = []
    all_doc_keys = list(raw_doc.keys())
    print(f"[COLLECT] AI response keys: {len(all_doc_keys)}", flush=True)
    if raw_doc.get("table_rows"):
        print(f"[COLLECT] table_rows: {len(raw_doc['table_rows'])} rows", flush=True)
        table_rows_raw.extend(raw_doc["table_rows"])
    # Collect any additional table arrays (multi-table templates)
    for key, val in raw_doc.items():
        if key.endswith("_rows") and key != "table_rows" and isinstance(val, list):
            print(f"[COLLECT] {key}: {len(val)} rows", flush=True)
            for row in val:
                if isinstance(row, dict):
                    row["_table_source"] = key.replace("_rows", "")
                    table_rows_raw.append(row)
    print(f"[COLLECT] total rows collected: {len(table_rows_raw)}", flush=True)

    # -- Bug 6: validate row/column alignment -----------------------------------
    alignment_warning = ""
    alignment_misaligned = False
    if table_rows_raw:
        table_rows_raw, alignment_misaligned, alignment_warning = _validate_row_alignment(
            table_rows_raw, regions.get("table_regions", [])
        )
        if alignment_misaligned:
            print(
                f"[BUG6] Alignment issue detected in {doc_ref(filename)} — "
                f"document will be flagged for review",
                flush=True,
            )

    # -- Fix page-break decimal splits -----------------------------------------
    extracted_fields_raw = _fix_split_decimals(extracted_fields_raw)
    table_rows_raw = [_fix_split_decimals_row(r) for r in table_rows_raw]

    # -- Normalize numeric and date values -------------------------------------
    extracted_fields_raw = _normalize_field_values(extracted_fields_raw)
    table_rows_raw = [_normalize_row_values(r) for r in table_rows_raw]

    # -- pdfplumber validation -------------------------------------------------
    # Skip cross-validation for scanned/image PDFs — pdfplumber returns empty text
    # for scanned docs, causing every correctly-extracted field to be flagged as
    # low confidence / needs_review even when the LLM was right.
    _skip_plumber_validation = not doc_text or len(doc_text.strip()) < 80
    if _skip_plumber_validation:
        validated_fields = {
            k: {"value": (v.get("value", "") if isinstance(v, dict) else str(v or "")),
                "confidence": "medium", "validated": True}
            for k, v in extracted_fields_raw.items()
        }
        validated_rows = [
            {col: {"value": str(val or ""), "confidence": "medium"}
             for col, val in row.items()}
            for row in table_rows_raw
        ]
        flagged = []
        validation = {"validated_fields": validated_fields, "validated_rows": validated_rows,
                      "flagged": [], "confidence_map": {}, "flag_count": 0}
    else:
        validation = _validate_with_pdfplumber(extracted_fields_raw, doc_text, table_rows_raw)
        validated_fields = validation["validated_fields"]
        validated_rows = validation["validated_rows"]
        flagged = validation["flagged"]

    # FIX 3: a schema-coercion warning escalates the document to needs_review
    # so a silently-unwritable AI response never passes as clean.
    if _schema_warn:
        flagged = list(flagged) + [{"ref": "_schema", "value": "", "reason": _schema_warn}]
        print(f"[SCHEMA] {doc_ref(filename)}: schema warning recorded as a flag", flush=True)

    # -- Build human-readable extracted_data -----------------------------------
    ref_to_label = {}
    for key, cell in cells.items():
        if not isinstance(cell, dict): continue
        val = cell.get("value", "").strip()
        is_extract = cell.get("extractTarget", False)
        if is_extract and val:
            parts = key.split(",")
            if len(parts) == 2:
                ref_to_label[_cell_ref(int(parts[0]), int(parts[1]))] = val

    for t in regions.get("explicit_targets", []):
        if t["ref"] not in ref_to_label:
            ref_to_label[t["ref"]] = t["label"]
    for kv in regions.get("kv_pairs", []):
        if kv["value_ref"] not in ref_to_label:
            ref_to_label[kv["value_ref"]] = kv["label"]
    for tc in regions.get("two_col_pairs", []):
        if tc["left_value_ref"] not in ref_to_label:
            ref_to_label[tc["left_value_ref"]] = tc["left_label"]
        if tc["right_value_ref"] not in ref_to_label:
            ref_to_label[tc["right_value_ref"]] = tc["right_label"]

    # Auto-resolve unlabelled refs
    for ref in validated_fields:
        if ref not in ref_to_label:
            try:
                col_str = "".join(ch for ch in ref if ch.isalpha()).upper()
                row_str = "".join(ch for ch in ref if ch.isdigit())
                c_idx = sum((ord(ch)-64)*(26**i) for i,ch in enumerate(reversed(col_str)))-1
                r_idx = int(row_str)-1
                left_val = (cells.get(f"{r_idx},{c_idx-1}") or {}).get("value","").strip() if c_idx>0 else ""
                above_val = (cells.get(f"{r_idx-1},{c_idx}") or {}).get("value","").strip() if r_idx>0 else ""
                ref_to_label[ref] = left_val or above_val or ref
            except Exception:
                ref_to_label[ref] = ref

    extracted_data = {}
    for ref, label in ref_to_label.items():
        vf = validated_fields.get(ref, {"value": "", "confidence": "high"})
        extracted_data[label] = {
            "value": vf.get("value", ""),
            "confidence": vf.get("confidence", "high"),
            "ref": ref,
        }

    # Static label cells
    for key, cell in cells.items():
        if not isinstance(cell, dict): continue
        val = cell.get("value","").strip()
        if val and not cell.get("extractTarget"):
            parts = key.split(",")
            if len(parts) == 2:
                ref = _cell_ref(int(parts[0]), int(parts[1]))
                extracted_data[f"_label_{ref}"] = {"value": val, "confidence": "high"}

    # Table rows - normalise
    # For multi-table docs, rows have _table_source set to identify which table they belong to.
    # Each table has its own column set — we must not merge columns across tables.
    normalised_rows = []
    if table_rows_raw:
        table_regions_list = regions.get("table_regions", [])

        # Build a map: table_source_key -> column_names for that table
        # table_source is set to the array key minus "_rows" (e.g. "earning_table")
        source_to_cols = {}
        for tr in table_regions_list:
            section = tr.get("section_label", "")
            import re as _re
            key = _re.sub(r'[^a-z0-9]', '_', section.lower()).strip('_')
            source_to_cols[key] = tr.get("column_names", [])

        # Also build merged col_names for single-table case
        all_col_names = []
        for tr in table_regions_list:
            all_col_names.extend(tr.get("column_names", []))
        all_col_names = list(dict.fromkeys(all_col_names))

        for row in table_rows_raw:
            if not isinstance(row, dict):
                continue

            # Determine which table this row belongs to
            table_source = row.get("_table_source", "")
            row_col_names = source_to_cols.get(table_source, all_col_names)

            if not row_col_names:
                row_col_names = [k for k in row.keys()
                                if not k.startswith("_")]

            # Filter ghost rows using THIS table's first column
            first_col = row_col_names[0] if row_col_names else None
            if first_col:
                first_val = str(row.get(first_col, "")).strip()
                if not first_val:
                    continue
                # Only skip rows that are clearly summary/total rows
                # Do NOT skip "tax" — it's a legitimate deduction type
                skip_kw = {"subtotal", "grand total", "shipping", "discount",
                           "charges", "refund", "balance due", "amount due"}
                if any(first_val.lower() == kw for kw in skip_kw):
                    continue
                # Skip rows where first value is ONLY a number (row number artifacts)
                if re.match(r'^\d{1,3}$', first_val):
                    continue

            # Build clean row with only this table's columns
            clean = {}
            for col in row_col_names:
                clean[col] = str(row.get(col, "") or "").strip()
            # Preserve table source for Excel writer
            if table_source:
                clean["_table_source"] = table_source

            normalised_rows.append(_normalise_values(clean, doc_type))

    has_table = bool(normalised_rows)
    overall_confidence = raw_doc.get("overall_confidence", "medium")

    r = DocumentExtractionResult(filename=filename)
    r.document_type = doc_type

    # Build per-table row maps using separate array keys
    per_table_rows = {}
    for tr in regions.get("table_regions", []):
        section = tr.get("section_label", "")
        key = re.sub(r'[^a-z0-9]', '_', section.lower()).strip('_') + "_rows"
        # Get rows for this table from the raw response
        raw_rows = raw_doc.get(key, [])
        if not raw_rows:
            # Fall back: filter table_rows_raw by Table field or _table_source
            raw_rows = [
                r2 for r2 in table_rows_raw
                if isinstance(r2, dict) and (
                    r2.get("Table", "").strip().lower() == section.strip().lower() or
                    r2.get("_table_source", "").replace("_", " ").strip().lower() in section.lower()
                )
            ]
        # Normalise these rows
        col_names = tr.get("column_names", [])
        normed = []
        for row in raw_rows:
            if isinstance(row, dict):
                clean = {col: str(row.get(col, "") or "").strip() for col in col_names}
                normed.append(_normalise_values(clean, doc_type))
        per_table_rows[key] = normed

    r.extracted_data = {
        "document_type": doc_type,
        "overall_confidence": overall_confidence,
        "extraction_method": "vision_primary",
        # FIX 4: persist the region analysis so export reuses it (no re-analysis)
        "template_regions": _regions_to_jsonable(regions),
        # template_type (labeled|mixed|structural) from the binding map — drives
        # deterministic export-writer routing (see _write_excel). Empty for legacy.
        "template_type": ((template_data.get("binding_map") or {})
                          .get("_meta", {}).get("template_type", "")),
        # COMPONENT 5: layout-mode "extract & place" output (empty for field-based)
        "layout_sections": (raw_doc.get("layout_sections")
                            if isinstance(raw_doc.get("layout_sections"), dict) else {}),
        # Section-aware column groups — used by the layout writer's column safety net
        "binding_column_groups": (template_data.get("binding_map", {})
                                  .get("_meta", {}).get("column_groups", [])),
        "table_mode": has_table and primary_mode == "table",
        "mixed_mode": has_table and primary_mode == "mixed",
        "table_rows": normalised_rows,
        "column_headers": [tr["column_names"] for tr in regions.get("table_regions",[])],
        "row_count": len(normalised_rows),
        "extracted_data": extracted_data,
        "extracted_fields": {k: v.get("value","") if isinstance(v,dict) else v
                              for k,v in validated_fields.items()},
        "segment_hint": seg_hint,
        "doc_index": doc_index,
        "validation": {
            "flagged_count": len(flagged),
            "flagged_fields": flagged,
            "confidence_map": validation.get("confidence_map", {}),
            "alignment_misaligned": alignment_misaligned,
            "alignment_warning": alignment_warning,
        },
        **per_table_rows,   # adds earning_table_rows, deduction_table_rows etc.
    }
    r.extraction_response = extraction
    r.processing_time_ms = elapsed
    r.success = True

    status = f"{len(flagged)} flags" if flagged else "clean"
    print(f"[EXTRACT] vision: {doc_ref(filename)} doc#{doc_index} -> "
          f"{len(extracted_data)} fields, {len(normalised_rows)} rows, "
          f"{overall_confidence} confidence, {status}", flush=True)
    return r


def _job_error_message(session, job_id, failed, produced):
    """The DOCUMENTS' own reasons, not a count of them.

    This used to read "N of M document(s) failed — open the job to see each
    document's error", and there is no per-document error view to open. The
    real reason was already being written to `DocumentResult.validation_errors`
    and returned by the API, and no component read it: a grep across the
    frontend found exactly one hit, the TypeScript type declaration. So a
    template the engine refused with "This template has no slots to fill.
    Every cell either contains text (a label) or is outside the used area..."
    surfaced in the UI as four hardcoded guesses about password-protected PDFs.

    Distinct messages, most common first, so five documents failing the same
    way say it once rather than five times.
    """
    if not produced:
        return "No documents were processed."

    head = f"{failed} of {produced} document(s) failed."
    try:
        rows = (session.query(DocumentResult)
                .filter(DocumentResult.job_id == job_id)
                .filter(DocumentResult.validation_errors != "")
                .all())
        counts = {}
        for r in rows:
            msg = (r.validation_errors or "").strip()
            if msg:
                counts[msg] = counts.get(msg, 0) + 1
        if not counts:
            return head
        ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        parts = [f"{m} ({n} documents)" if n > 1 else m for m, n in ranked[:3]]
        if len(ranked) > 3:
            parts.append(f"and {len(ranked) - 3} other error(s)")
        return head + " " + " ".join(parts)
    except Exception as e:
        # A summary line must never be the reason a job's status is lost.
        print(f"[THREAD] could not summarise document errors: {exc_brief(e)}", flush=True)
        return head


def _fail(filename, error):
    from orchestrator import DocumentExtractionResult
    r = DocumentExtractionResult(filename=filename)
    r.error = error; r.processing_time_ms = 0; r.success = False
    return r
