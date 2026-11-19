"""Offline drivers over Run A's real engine seams and frozen responses.

No function in this module owns a provider client. The ``llm`` object handed
to the extractor is a local scripted function whose first answer is the exact
``raw_llm_responses`` text captured in the committed job record.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tests.harness import bootstrap as bs

bs.bootstrap()

import llm_contract as C  # noqa: E402
from connectors.base import LLMResponse  # noqa: E402


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures" / "acceptance"
RECORDS = FIXTURES / "job_records"
DOCS = FIXTURES / "source_docs"
XLSX = FIXTURES / "templates" / "DocAgent_templates_v2.xlsx"

CASES = {
    15: ("bank_statement/flowparse_bank_us.pdf", "Bank_Recon", "bank_statement"),
    19: ("purchase_order/flowparse_po.pdf", "PO_Full", "purchase_order"),
    21: ("w2/irs_w2_mod11.pdf", "W2_Full", "w2"),
    25: ("1099/irs_1099nec_ellis.pdf", "F1099_NEC_MISC", "form_1099"),
}


def load_record(job: int) -> dict:
    records = json.loads((RECORDS / f"job{job}.json").read_text(encoding="utf-8"))
    assert len(records) == 1
    return records[0]


def frozen_raw(job: int) -> str:
    return load_record(job)["extracted_data"]["raw_llm_responses"][0]


def template_grid(sheet: str) -> dict:
    import openpyxl

    ws = openpyxl.load_workbook(XLSX, data_only=False)[sheet]
    cells = {
        f"{cell.row - 1},{cell.column - 1}": {"value": str(cell.value)}
        for row in ws.iter_rows()
        for cell in row
        if cell.value is not None and str(cell.value).strip()
    }
    merges = {
        f"{merged.min_row - 1},{merged.min_col - 1}": {
            "rows": merged.max_row - merged.min_row + 1,
            "cols": merged.max_col - merged.min_col + 1,
        }
        for merged in ws.merged_cells.ranges
    }
    return {"cells": cells, "merges": merges, "colWidths": [], "repeatRows": []}


def replay_job(job: int, answer_for_call=None) -> dict:
    """Replay one frozen job through ``run_slot_extraction``.

    ``answer_for_call`` may return a dict/None for targeted retry experiments.
    With no override, every call receives the frozen answer, proving that a
    failed targeted second request cannot turn the document READY.
    """
    from core.preprocessor import preprocess_file
    from slot_extractor import run_slot_extraction

    relative_path, sheet, document_type = CASES[job]
    source_path = DOCS / relative_path
    document = preprocess_file(source_path)
    raw = frozen_raw(job)
    parsed = json.loads(raw)
    calls = []

    def extract(**kwargs):
        calls.append(kwargs)
        answer = (answer_for_call(len(calls), kwargs, parsed)
                  if answer_for_call else parsed)
        if answer is None:
            return LLMResponse(
                raw_text="", parsed_json=None, success=False,
                error="mock: no answer", error_kind=C.INVALID_JSON,
                model_used="offline-frozen-response",
            )
        text = raw if answer is parsed else json.dumps(answer)
        return LLMResponse(
            raw_text=text, parsed_json=answer, success=True,
            model_used="offline-frozen-response",
        )

    page_count = len(document.page_texts)
    with C.collect_attempts(fresh=True):
        result = run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)),
            source_path,
            {"layout": template_grid(sheet)},
            None,
            page_images=[],
            doc_text=document.extracted_text,
            doc_text_pages=document.page_texts,
            file_type="digital_pdf",
            default_doc_type=document_type,
            start=0.0,
            page_lines=document.page_lines,
            page_origins={i + 1: origin for i, origin in enumerate(document.page_origins)},
            page_numbers=list(range(1, page_count + 1)),
            widget_values=document.widget_values,
            unreadable={
                "ocr_failed": document.ocr_failed_pages,
                "ocr_zero": document.ocr_zero_word_pages,
            },
        )[0]
    return {
        "job": job,
        "record": load_record(job),
        "raw": raw,
        "document": document,
        "calls": calls,
        "result": result,
        "extracted_data": result.extracted_data,
    }


def words(page_no: int, texts) -> list[list[dict]]:
    """Synthetic visual lines with the same word geometry the engine reads."""
    from text_layer import stamp_page

    output = []
    for line_index, text in enumerate(texts):
        cells = text if isinstance(text, tuple) else (text,)
        line = []
        for column, cell in enumerate(cells):
            x = (40.0, 160.0, 320.0, 420.0)[column] if isinstance(text, tuple) else 40.0
            for token in str(cell).split():
                line.append({
                    "text": token,
                    "x0": x,
                    "x1": x + 6 * len(token),
                    "top": 50.0 + 14 * line_index,
                    "bottom": 60.0 + 14 * line_index,
                })
                x += 6 * len(token) + 6
        output.append(line)
    stamp_page(output, page_no)
    return output


BAND_GRID = {
    "cells": {
        "0,0": {"value": "Date"},
        "0,1": {"value": "Description"},
        "0,2": {"value": "Amount"},
    },
    "merges": {}, "colWidths": [], "repeatRows": [],
}


def model_response(answer: dict | None, *, error_kind=None) -> LLMResponse:
    return LLMResponse(
        raw_text=json.dumps(answer) if answer is not None else "",
        parsed_json=answer,
        success=answer is not None,
        error_kind=error_kind,
        error="" if answer is not None else f"offline failure: {error_kind}",
        model_used="offline-scripted-response",
    )


def run_synthetic(extract, pages_text, *, origins=None, unreadable=None,
                  grid=None) -> dict:
    """Run the real slot extractor over deterministic geometric page lines."""
    from slot_extractor import run_slot_extraction
    from text_layer import text_from_lines

    page_lines = [words(index + 1, text) for index, text in enumerate(pages_text)]
    page_texts = [text_from_lines(lines) for lines in page_lines]
    page_count = len(page_lines)
    with C.collect_attempts(fresh=True):
        result = run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)),
            "offline-fixture.pdf",
            {"layout": grid or BAND_GRID},
            None,
            page_images=[],
            doc_text="\n\n".join(page_texts),
            doc_text_pages=page_texts,
            file_type="digital_pdf",
            default_doc_type="other",
            start=0.0,
            page_lines=page_lines,
            page_origins=origins or {i + 1: "native" for i in range(page_count)},
            page_numbers=list(range(1, page_count + 1)),
            unreadable=unreadable,
        )[0]
    return result.extracted_data
