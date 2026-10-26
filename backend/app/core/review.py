"""
Review — what a person must still check, decided in ONE place.

The engine marks every value with a confidence level and, where something is
owed, `review_required` plus `review_reasons` (docs/OCR-READER-SEAM-DESIGN.md
§12). This module turns that into the three things the review screen and the
export both need, so the two can never disagree:

* `REASONS` — every reason code, as a short label and a longer explanation.
  An unknown code is never hidden: `reason_text` falls back to the raw code.
* `value_status` — the review status of one value: `verified`, `grounded`,
  `unverified`, `low`, `edited`, `empty_flagged`, `empty` or `unknown`, and
  whether it is still UNRESOLVED.
* `document_values` / `summarise` — every value of a stored result, and the
  counts the screen and the export header show.

A value is unresolved when it needs a person and no person has dealt with it:
its level is `unverified`, `low` or unrecognised, or it is empty and flagged,
or it carries `review_required` — and it has been neither edited nor marked
reviewed (on the value, or the whole document). `verified` and `grounded`
values that owe nothing are resolved by the checks themselves.

Review marks live inside the stored result (`extraction_json`), so no schema
change is needed: `field_provenance[ref]["reviewed"]`, a row's `_reviewed`,
and `review.document_reviewed` for a whole document.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from app.core.confidence import EDITED, GROUNDED, HIGH, LOW, UNVERIFIED

#: code -> (label, tooltip). The label fits a badge; the tooltip says what
#: happened and what to check. Keep in step with §12 of
#: docs/OCR-READER-SEAM-DESIGN.md (tests/test_review_reasons.py enforces it).
REASONS: dict[str, tuple[str, str]] = {
    "ocr_origin": (
        "Read from a scan, please verify",
        "The page had no text layer and was read by OCR. A misread character "
        "would still match the OCR text, so compare this value with the image."),
    "pre_ocr_origin": (
        "Read from an embedded OCR layer",
        "The page's text is a scanner's OCR reading laid over an image, not "
        "the document's own text. Compare this value with the image."),
    "grounding_failed": (
        "Not found on the page as quoted",
        "The words the value was read from could not be found on the page, "
        "or were assembled from words that are not next to each other."),
    "placement_failed": (
        "Sits under a different column",
        "The value is printed under another column than the one it was "
        "written to, or it joins two side-by-side blocks."),
    "content_check_failed": (
        "More than one piece of information",
        "The cell holds something besides the value it asks for, such as an "
        "email address, a phone number or a sentence around a date or amount."),
    "checksum_failed": (
        "Routing number failed its check digit",
        "These nine digits fail the ABA routing-number checksum, so they "
        "cannot be a routing number as read."),
    "amount_mismatch": (
        "Amount in figures and in words disagree",
        "The cheque's amount in figures and its amount in words both read "
        "clearly and do not match. Either could be wrong."),
    "amount_unreadable": (
        "Figures/words check could not be completed",
        "One of the cheque's two amounts could not be read with certainty, so "
        "they could not be compared."),
    "micr_band_unreadable": (
        "MICR line could not be read",
        "The cheque's MICR band is there but none of its digits could be "
        "read, so the routing and account numbers are not confirmed by it."),
    "totals_mismatch": (
        "Invoice totals do not add up",
        "The line items do not sum to the subtotal, or subtotal + charges + "
        "tax - discount does not equal the total (within one cent)."),
    "totals_unreadable": (
        "Invoice totals could not be checked",
        "A value the totals check needs is not a plain amount (for example "
        "'TBD' or a percentage)."),
    "balance_mismatch": (
        "Statement balances do not add up",
        "Opening balance + credits - debits does not equal the closing "
        "balance, or a row's balance does not follow from the one before it."),
    "balance_unreadable": (
        "Statement balances could not be checked",
        "A value the balance check needs is not a plain amount (for example "
        "'12.00 CR')."),
    "payslip_mismatch": (
        "Payslip totals do not add up",
        "Gross pay - total deductions does not equal net pay, or the listed "
        "deductions do not sum to the total deductions (within one cent)."),
    "payslip_unreadable": (
        "Payslip totals could not be checked",
        "A value the payslip check needs is not a plain amount."),
    "receipt_mismatch": (
        "Receipt totals do not add up",
        "The items do not sum to the subtotal, or subtotal + tax + tip/fees - "
        "discount does not equal the total (within one cent)."),
    "receipt_unreadable": (
        "Receipt totals could not be checked",
        "A value the receipt check needs is not a plain amount."),
    "thin_text_layer": (
        "Page text may be incomplete",
        "An image covers this page and its text layer could not be compared "
        "with an OCR reading, so the text may carry only part of the page."),
    "possible_multiple_documents": (
        "May contain more than one document",
        "The engine could not establish how many documents (or cheques) "
        "this record holds and kept it as one rather than guess a split. The "
        "notes say at which page a new one may begin."),
    "possible_duplicate": (
        "Possible duplicate",
        "Another record in this batch looks like the same cheque (same bank, "
        "account and serial number). Check it was not scanned twice."),
    "number_ambiguous": (
        "Number format is ambiguous",
        "This could be a thousands separator or a decimal point, and nothing on the document says which. The text is kept as printed; set the template's or firm's locale, or check the value."),
    "minor_units_mismatch": (
        "Decimals do not fit the currency",
        "The amount has more or fewer decimal places than its currency uses. Check the amount and the currency."),
    "date_ambiguous": (
        "Day and month could be swapped",
        "This date reads one way in the US and another elsewhere, and nothing on the document says which. Check it, or set the template's or firm's locale."),
    "date_unreadable": (
        "Date in another script",
        "The date uses digits the engine does not read. Check it against the document."),
    "non_english_text": (
        "Not English — not checked",
        "This value was read from text in another language or script. The engine's checks only understand English, so compare it with the document."),
    "currency_mismatch": (
        "Amounts in different currencies",
        "These amounts are added or compared, but they are in different currencies. Check which currency each one is in."),
    "currency_ambiguous": (
        "Currency unclear",
        "These amounts may be in different currencies (for example US and Canadian dollars). Check the currency of each."),
    "iban_invalid": (
        "IBAN is not valid",
        "The IBAN fails its length or check-digit test, so at least one character is wrong."),
    "swift_invalid": (
        "SWIFT/BIC is not valid",
        "The SWIFT/BIC code is not in the right format or names no country."),
    "sort_code_invalid": (
        "Sort code is not valid",
        "A UK sort code is six digits (12-34-56)."),
    "gstin_invalid": (
        "GSTIN is not valid",
        "The GSTIN fails its format or its check character, so at least one character is wrong."),
    "pan_invalid": (
        "PAN is not valid",
        "The PAN is not in the right format."),
    "pan_gstin_mismatch": (
        "PAN does not match the GSTIN",
        "A GSTIN contains its holder's PAN; these two do not agree, so one of them is wrong."),
    "ifsc_invalid": (
        "IFSC is not valid",
        "An IFSC is 4 letters, a zero, then 6 letters or digits."),
    "vat_format_invalid": (
        "VAT number format is wrong",
        "This VAT number does not have the format its country prefix requires."),
    "trn_invalid": (
        "TRN is not valid",
        "A UAE TRN is 15 digits."),
    "ein_invalid": (
        "EIN is not valid",
        "A US EIN is nine digits (12-3456789) with an assigned prefix."),
    "category_uncertain": (
        "Category not certain",
        "No single category rule fits this row. Choose its category, or add a rule to the template or firm list."),
    "row_count_mismatch": (
        "Transaction count does not match",
        "The statement says how many transactions it has, and a different number of rows was read. A row may have been missed or added."),
    "rule_failed": (
        "Template rule failed",
        "A check written into this template did not hold for these values (the rule's name follows). One of them is probably wrong."),
    "rule_unreadable": (
        "Template rule not checked",
        "A check written into this template could not be applied to these values (the rule's name follows), so they were not checked by it."),
    "void_marker": (
        "Marked void or copy",
        "The document is stamped VOID, SPECIMEN, COPY or similar. Its values are shown for checking only."),
    "paid_marker": (
        "Stamped PAID",
        "The document is stamped PAID. Check it has not already been settled before acting on it."),
    "redacted_or_obscured": (
        "Painted over or unreadable",
        "Part of the page is blacked out or too dark to read. This value may be there but could not be read, and nothing was guessed."),
}


def reason_text(code: str) -> tuple[str, str]:
    """(label, tooltip) for a code; an unknown code shows itself. A declared
    rule's code carries the rule's name (`rule_failed:lines_sum`), shown in
    the label."""
    if code in REASONS:
        return REASONS[code]
    base, _, name = str(code).partition(":")
    if name and base in REASONS:
        label, tip = REASONS[base]
        return (f"{label} ({name})", tip)
    return (f"Needs review ({code})",
            f"Reason code '{code}' has no description yet. The value still "
            f"needs review.")


#: status -> (label, meaning). The status is what the badge and the export
#: show; the level is the engine's claim it is derived from.
STATUSES: dict[str, tuple[str, str]] = {
    "verified": ("Verified", "Found on the page as quoted, under a label you wrote."),
    "grounded": ("Grounded", "Found on the page as quoted; the label was named by the model."),
    "unverified": ("Unverified", "Machine-read (a scan or an image); compare with the page."),
    "low": ("Low", "A check failed; this value is probably wrong."),
    "edited": ("Edited", "Typed by a person."),
    "empty_flagged": ("Empty, flagged", "Nothing was extracted, and something says a value was expected."),
    "empty": ("Empty", "Nothing was extracted."),
    "unknown": ("Unknown", "The value carries no recognised confidence level."),
}

_LEVEL_STATUS = {HIGH: "verified", GROUNDED: "grounded", UNVERIFIED: "unverified",
                 LOW: "low", EDITED: "edited"}
_NEEDS_PERSON = {"unverified", "low", "empty_flagged", "unknown"}


def value_status(value: Any, level: Optional[str], *, review_required: bool = False,
                 reasons: Iterable[str] = (), flagged: bool = False,
                 reviewed: bool = False) -> dict:
    """The review status of one value.

    `resolved` is False while a person still owes it a look."""
    reasons = [str(r) for r in (reasons or [])]
    empty = value is None or str(value).strip() == ""
    if level == EDITED:
        status = "edited"
    elif empty:
        status = "empty_flagged" if (flagged or review_required or reasons) else "empty"
    else:
        status = _LEVEL_STATUS.get(str(level or ""), "unknown")
    owes = status in _NEEDS_PERSON or bool(review_required)
    resolved = status == "edited" or bool(reviewed) or not owes
    return {"status": status, "reasons": reasons, "review_required": bool(review_required),
            "reviewed": bool(reviewed), "resolved": resolved}


def table_keys(ed: dict) -> list[tuple[str, str]]:
    """(table name, result key) for every table of a stored result."""
    out, seen = [], set()
    for t in ((ed.get("slot_map") or {}).get("tables") or []):
        name = str(t.get("name") or "table")
        key = f"{name}_rows"
        if key not in seen:
            out.append((name, key)); seen.add(key)
    for key, rows in ed.items():
        if (isinstance(key, str) and key.endswith("_rows") and key not in seen
                and isinstance(rows, list) and rows):
            out.append((key[: -len("_rows")], key)); seen.add(key)
    return out


def _flagged_labels(ed: dict) -> set[str]:
    flags = (ed.get("validation") or {}).get("flagged_fields") or []
    return {str(f.get("ref")) for f in flags if isinstance(f, dict) and f.get("ref")}


def document_reviewed(ed: dict) -> bool:
    return bool((ed.get("review") or {}).get("document_reviewed"))


def document_values(ed: dict) -> list[dict]:
    """Every value of a stored result with its status, fields first, then
    each table's cells in row order. A legacy result with no slot map
    contributes its label projection only."""
    if not isinstance(ed, dict):
        return []
    doc_ok = document_reviewed(ed)
    flagged = _flagged_labels(ed)
    cmap = (ed.get("validation") or {}).get("confidence_map") or {}
    prov = ed.get("field_provenance") or {}
    fields = ed.get("extracted_fields") or {}
    labels = {str(f.get("ref")): f.get("row_label") or f.get("ref")
              for f in ((ed.get("slot_map") or {}).get("fields") or []) if f.get("ref")}
    out = []
    refs = list(labels) + [r for r in fields if r not in labels]
    if refs:
        for ref in refs:
            p = prov.get(ref) or {}
            label = labels.get(ref, ref)
            v = fields.get(ref, "")
            st = value_status(v, _image_level(ed, cmap.get(ref)),
                              review_required=bool(p.get("review_required")),
                              reasons=p.get("review_reasons") or [],
                              flagged=label in flagged or ref in flagged,
                              reviewed=doc_ok or bool(p.get("reviewed")))
            out.append({"kind": "field", "ref": ref, "label": label, "value": v,
                        "level": cmap.get(ref), "page": p.get("page"),
                        "source": p.get("source"), **st})
    else:
        for label, e in (ed.get("extracted_data") or {}).items():
            if not isinstance(e, dict):
                continue
            st = value_status(e.get("value"), e.get("confidence"),
                              flagged=label in flagged, reviewed=doc_ok)
            out.append({"kind": "field", "ref": e.get("ref"), "label": label,
                        "value": e.get("value"), "level": e.get("confidence"),
                        "page": None, "source": None, **st})
    for name, key in table_keys(ed):
        for i, row in enumerate(ed.get(key) or []):
            if not isinstance(row, dict):
                continue
            ungrounded = set(row.get("_ungrounded") or [])
            edited = set(row.get("_edited") or [])
            for col, v in row.items():
                if str(col).startswith("_"):
                    continue
                level = _image_level(ed, EDITED if col in edited else (
                    LOW if col in ungrounded else row.get("_confidence")))
                st = value_status(v, level, review_required=bool(row.get("_review_required")),
                                  reasons=row.get("_review_reasons") or [],
                                  reviewed=doc_ok or bool(row.get("_reviewed")))
                if st["status"] in ("empty", "empty_flagged"):
                    continue          # a blank cell in a row is not a value
                out.append({"kind": "cell", "table": name, "row": i, "column": col,
                            "ref": None, "label": f"{name} row {i + 1}: {col}",
                            "value": v, "level": level, "page": row.get("_page"),
                            "source": row.get("_source"), **st})
    out.extend(category_values(ed, doc_ok))
    return out


def category_values(ed: dict, doc_ok: bool = False) -> list[dict]:
    """The categories the option assigned (engine/categorize.py), as values
    with the SAME status rules as any other: a rule hit is `grounded`, a model
    guess `unverified` (owes review), "Uncategorized" carries its reason. A
    category is resolved when its row (or the document) is marked reviewed."""
    out = []
    keys = dict(table_keys(ed))
    for name, entries in (ed.get("categories") or {}).items():
        rows = ed.get(keys.get(name, f"{name}_rows")) or []
        for e in entries or []:
            if not isinstance(e, dict) or not isinstance(e.get("row"), int):
                continue
            row = rows[e["row"]] if 0 <= e["row"] < len(rows) and isinstance(rows[e["row"]], dict) else {}
            reasons = list(e.get("reasons") or [])
            st = value_status(e.get("category"), e.get("level"),
                              review_required=bool(reasons) or e.get("by") == "model",
                              reasons=reasons, reviewed=doc_ok or bool(row.get("_reviewed")))
            how = {"rule": f"{e.get('rule')} rule matched {e.get('matched')!r}",
                   "model": "suggested by the model, not checked"}.get(e.get("by"), e.get("note", ""))
            out.append({"kind": "category", "table": name, "row": e["row"], "column": "Category",
                        "ref": None, "label": f"{name} row {e['row'] + 1}: Category",
                        "value": e.get("category"), "level": e.get("level"),
                        "page": row.get("_page"), "source": how, **st})
    return out


# ── lookups for the export writers ───────────────────────────────────────────
#: Writers that lay values out by template address (the legacy form, table,
#: mixed and layout writers, the combined and per-file sheets) ask for ONE
#: value's status at the moment they write it. These gather the inputs; the
#: status itself is `value_status`, the function the screen uses.

_MISSING = object()


def _image_level(ed: dict, level):
    """An image upload has no text layer: nothing in it was checked, whatever
    level a legacy record carries. An edit is still an edit."""
    if ed.get("image_upload") and level != EDITED:
        return UNVERIFIED
    return level


def field_status(ed: Any, ref: Optional[str] = None, label: Optional[str] = None,
                 value: Any = _MISSING) -> dict:
    """The status of one field value, found by template ref and/or label."""
    ed = ed if isinstance(ed, dict) else {}
    cmap = (ed.get("validation") or {}).get("confidence_map") or {}
    prov = ed.get("field_provenance") or {}
    fields = ed.get("extracted_fields") or {}
    inner = ed.get("extracted_data") or {}
    entry = inner.get(label) if label is not None else None
    if not isinstance(entry, dict):
        entry = None
        if ref is not None:
            entry = next((e for e in inner.values() if isinstance(e, dict)
                          and str(e.get("ref")) == str(ref)), None)
    if ref is None and entry:
        ref = entry.get("ref")
    p = prov.get(ref) if ref is not None else None
    p = p if isinstance(p, dict) else {}
    level = cmap.get(ref) if ref is not None else None
    if level is None and entry:
        level = entry.get("confidence")
    if p.get("edited"):
        level = EDITED
    level = _image_level(ed, level)
    if value is _MISSING:
        value = fields.get(ref) if ref in fields else (entry or {}).get("value", "")
    if isinstance(value, dict):
        value = value.get("value", "")
    flagged = _flagged_labels(ed)
    return value_status(value, level,
                        review_required=bool(p.get("review_required")),
                        reasons=p.get("review_reasons") or [],
                        flagged=str(ref) in flagged or (label is not None and str(label) in flagged),
                        reviewed=document_reviewed(ed) or bool(p.get("reviewed")))


def row_cell_status(ed: Any, row: Any, col: str) -> dict:
    """The status of one table cell, from the row dict it was written from.
    A legacy row with no `_confidence` is `unknown`, which needs review."""
    ed = ed if isinstance(ed, dict) else {}
    row = row if isinstance(row, dict) else {}
    v = row.get(col, "")
    level = row.get("_confidence")
    if isinstance(v, dict):
        level = v.get("confidence") or level
        v = v.get("value", "")
    if col in set(row.get("_ungrounded") or []):
        level = LOW
    if col in set(row.get("_edited") or []):
        level = EDITED
    level = _image_level(ed, level)
    return value_status(v, level, review_required=bool(row.get("_review_required")),
                        reasons=row.get("_review_reasons") or [],
                        reviewed=document_reviewed(ed) or bool(row.get("_reviewed")))


def layout_values(ed: Any) -> list[dict]:
    """The values of a LEGACY layout result (`layout_sections`), which the
    layout writer exports and `document_values` does not list: no review
    route can address them, but an export must still count and mark them."""
    out = []
    ls = ed.get("layout_sections") if isinstance(ed, dict) else None
    for name, sec in (ls.items() if isinstance(ls, dict) else []):
        for i, row in enumerate((sec or {}).get("rows") or [] if isinstance(sec, dict) else []):
            if not isinstance(row, dict) or row.get("value") in (None, ""):
                continue
            st = row_cell_status(ed, {"value": row.get("value"),
                                      "_confidence": row.get("confidence")}, "value")
            out.append({"kind": "cell", "table": f"layout:{name}", "row": i,
                        "column": "value", "ref": None,
                        "label": f"{name} row {i + 1}", "value": row.get("value"),
                        "level": row.get("confidence"), "page": None,
                        "source": None, **st})
    return out


def export_values(ed: Any) -> list[dict]:
    """Every value an export can write: `document_values` plus legacy layout
    rows. What the Legend sheet counts."""
    return document_values(ed) + layout_values(ed)


def summarise(values: list[dict]) -> dict:
    """Counts for a header line: how many values still need a person."""
    unresolved = [v for v in values if not v["resolved"]]
    return {"values": len(values),
            "needs_review": len(unresolved),
            "low": sum(1 for v in unresolved if v["status"] == "low"),
            "unverified": sum(1 for v in unresolved if v["status"] == "unverified"),
            "empty_flagged": sum(1 for v in unresolved if v["status"] == "empty_flagged")}


# ── export marks ─────────────────────────────────────────────────────────────
#: Fill per status in an exported sheet (ARGB). A value that owes nothing has
#: no fill; every other status is coloured AND explained in a cell comment, so
#: the mark survives a black-and-white print and a colour-blind reader.
EXPORT_FILLS = {
    "low": "FFFFC7CE",            # red
    "unverified": "FFFFEB9C",     # amber
    "unknown": "FFFFEB9C",
    "empty_flagged": "FFD9D9D9",  # grey
    "needs_review": "FFFFEB9C",   # a confident level that still owes a look
    "edited": "FFE4DFEC",         # lavender
    "reviewed": "FFE2EFDA",       # pale green
}


def export_mark(st: dict) -> Optional[tuple[str, str, str]]:
    """(row status word, fill, comment text) for one exported value, or None
    when the value is clean (verified or grounded, nothing owed)."""
    status = st["status"]
    reasons = [reason_text(r)[0] for r in st.get("reasons") or []]
    why = ("; ".join(reasons)) if reasons else STATUSES.get(status, (status, ""))[1]
    if status == "edited":
        return ("Edited", EXPORT_FILLS["edited"], "EDITED BY HAND — typed by a person, "
                "not extracted.")
    if st["resolved"]:
        if st.get("reviewed") and (status in _NEEDS_PERSON or st.get("review_required")):
            return ("Reviewed", EXPORT_FILLS["reviewed"],
                    f"REVIEWED by a person. Machine status was "
                    f"{STATUSES.get(status, (status,))[0]}: {why}")
        return None
    key = status if status in EXPORT_FILLS else "needs_review"
    label = STATUSES.get(status, (status,))[0]
    return ("Needs review", EXPORT_FILLS[key], f"NEEDS REVIEW — {label}: {why}")


#: The legend sheet, one row per mark.
LEGEND = [
    ("No fill", None, "Verified or grounded: found on the page as quoted, nothing owed."),
    ("Red", EXPORT_FILLS["low"], "Low: a check failed; the value is probably wrong."),
    ("Amber", EXPORT_FILLS["unverified"], "Unverified or needs review: machine-read "
     "(a scan or an image), or a check could not be completed."),
    ("Grey", EXPORT_FILLS["empty_flagged"], "Empty, flagged: nothing was extracted where "
     "a value was expected."),
    ("Lavender", EXPORT_FILLS["edited"], "Edited by hand."),
    ("Pale green", EXPORT_FILLS["reviewed"], "Reviewed and accepted by a person."),
]
