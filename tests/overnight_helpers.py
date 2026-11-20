"""Shared helpers for the overnight-run reproductions (tests/test_overnight_*.py).

Every model answer is scripted and replayed through the real post-model
pipeline (``run_slot_extraction``) with the real PDF's text and geometry, the
same seam ``tests/test_batch2_failure_classes.py`` uses. No network.
"""

from __future__ import annotations

import copy
import json
from functools import lru_cache
from types import SimpleNamespace

from tests.contract import run_a_driver as D  # noqa: F401  (bootstraps imports)
from tests.local_corpus import local_file

import llm_contract as C  # noqa: E402
from connectors.base import LLMResponse  # noqa: E402


@lru_cache(maxsize=None)
def document(relative: str):
    from core.preprocessor import preprocess_file
    return preprocess_file(local_file(relative))


def grid(cells: dict, regions=None) -> dict:
    return {"cells": {k: {"value": v, "style": {}} for k, v in cells.items()},
            "merges": {}, "colWidths": [], "repeatRows": [],
            "regions": regions or []}


def column_grid(labels, tables=()):
    """Labels down column A (a key/value template); each table is
    (title, [headers], reserved_rows) placed below, declared as a region."""
    cells, regions = {}, []
    row = 0
    for label in labels:
        cells[f"{row},0"] = label
        row += 1
    for title, headers, reserved in tables:
        row += 1
        cells[f"{row},0"] = title
        row += 1
        for c, h in enumerate(headers):
            cells[f"{row},{c}"] = h
        regions.append({"type": "table", "name": title, "orientation": "rows",
                        "r1": row, "c1": 0, "r2": row + reserved,
                        "c2": max(1, len(headers) - 1)})
        row += reserved + 1
    return grid(cells, regions)


def slots(g):
    from slot_extractor import enumerate_slots
    return enumerate_slots(g)


def field_id(g, label):
    for f in slots(g)["fields"]:
        if f["row_label"] == label:
            return f["slot_id"]
    raise AssertionError((label, [f["row_label"] for f in slots(g)["fields"]]))


def table_name(g, title):
    names = [t["name"] for t in slots(g)["tables"]]
    for n in names:
        if n == title or title.casefold() in n.casefold():
            return n
    raise AssertionError((title, names))


def run(relative, g, answer, *, doc_type="other", answers=None):
    """Replay `answer` (or the list `answers`, one per call) through the real
    pipeline for the local PDF `relative`. Returns (extracted_data, calls)."""
    from slot_extractor import run_slot_extraction

    doc = document(relative)
    queue = [copy.deepcopy(a) for a in (answers or [answer])]
    calls = []

    def extract(**kwargs):
        calls.append(kwargs)
        parsed = queue.pop(0) if len(queue) > 1 else copy.deepcopy(queue[0])
        return LLMResponse(raw_text=json.dumps(parsed), parsed_json=parsed,
                           success=True, model_used="offline-overnight-scripted")

    n = len(doc.page_texts)
    with C.collect_attempts(fresh=True):
        result = run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)),
            local_file(relative), {"layout": g}, None,
            page_images=[], doc_text=doc.extracted_text,
            doc_text_pages=doc.page_texts, file_type=doc.file_type,
            default_doc_type=doc_type, start=0.0, page_lines=doc.page_lines,
            page_origins={i + 1: o for i, o in enumerate(doc.page_origins)},
            page_numbers=list(range(1, n + 1)),
            widget_values=doc.widget_values, form_fields=doc.form_fields,
            unreadable={"ocr_failed": doc.ocr_failed_pages,
                        "ocr_zero": doc.ocr_zero_word_pages},
        )[0]
    return result.extracted_data, calls


def value(data, label) -> str:
    entry = (data.get("extracted_data") or {}).get(label)
    if isinstance(entry, dict):
        return str(entry.get("value") or "")
    return str(entry or "")


def level(data, label) -> str:
    entry = (data.get("extracted_data") or {}).get(label)
    return str(entry.get("confidence") or "") if isinstance(entry, dict) else ""


def flags(data) -> list:
    return list((data.get("validation") or {}).get("flagged_fields") or [])


def flag_text(data) -> str:
    return " ".join(f"{f.get('ref', '')} {f.get('value', '')} {f.get('reason', '')}"
                    for f in flags(data) if isinstance(f, dict)).casefold()


def flagged_refs(data) -> set:
    return {str(f.get("ref")) for f in flags(data) if isinstance(f, dict)}


def reasons(data) -> list:
    return [str(a.get("text") or a) for a in data.get("attention") or []]


def ans(v, source, page=1):
    return {"value": v, "source": source, "page": page}
