"""
Tests that reproduce KNOWN, UNFIXED production bugs. They FAIL on purpose —
they are the proof the harness can see the bug. Do not "fix" the tests;
fix the bug and they go green.

Deselect with:  pytest -m "not known_bug"

── P3: fabricated duplicate line item on the structural path ─────────────────

Audit 2026-08-17 §6.4, reproduced live 4/4 on the committed
BalanceSheet-synth.pdf under production config. Mechanism:

  1. Layer 1 emits phantom sections "Total Current Assets" /
     "Total Current Liabilities" (item_count=1) alongside the real sections.
  2. Layer 2, asked to extract the phantom, returns the whole column (5 rows).
  3. S5 truncation (extractor.py ~:369) keeps rows[:1] — the section's FIRST
     LINE ITEM (Cash & Cash Equivalents), not its total.
  4. The writer's _match_group substring test routes "Total Current Assets"
     into the real "Current Assets" group and appends the row.
  5. Neither dedup guard fires: content-signature needs identical content
     (1 row != 4); superset dedup needs len(r1) > len(r2) and the truncated
     phantom is a SUBSET.

Result: the exported sheet contains a duplicate "Cash & Cash Equivalents /
168000" row that is not in the source document.

The LLM trigger is nondeterministic, so this test replays the DOCUMENTED
Layer-1/Layer-2 responses (exactly the section list and row counts observed
live in the audit) through the REAL deterministic pipeline: S5 truncation,
section matching, dedup guards, and the real layout writer. Everything below
the mocked LLM boundary is production code.
"""
import contextlib
import io
import json

import pytest

from tests.harness import bootstrap as bs

pytestmark = pytest.mark.known_bug

FIXTURE_PDF = bs.BACKEND_DIR / "data" / "test_uploads" / "BalanceSheet-synth.pdf"
FIXTURE_TEMPLATE = bs.BACKEND_DIR / "data" / "test_uploads" / "bs_unlabeled_template.json"

ASSET_ROWS = [
    ("Cash & Cash Equivalents", "168000"),
    ("Accounts Receivable", "95000"),
    ("Inventory", "140000"),
    ("Prepaid Expenses", "12000"),
]
LIAB_ROWS = [
    ("Accounts Payable", "262000"),
    ("Short-Term Debt", "80000"),
    ("Accrued Expenses", "33000"),
    ("Deferred Revenue", "25000"),
]

# Layer-1 document map exactly as observed live (audit §6.4):
# the two totals rows promoted to phantom sections with item_count=1.
L1_DOCUMENT_MAP = {
    "file_type": "digital_pdf",
    "total_documents": 1,
    "documents": [{
        "doc_index": 0, "doc_type": "balance_sheet", "pages": [0],
        "identifier": "BalanceSheet-synth",
        "sections": [
            {"heading": "Current Assets", "page": 0, "item_count": 4, "structure": "table"},
            {"heading": "Current Liabilities", "page": 0, "item_count": 4, "structure": "table"},
            {"heading": "Total Current Assets", "page": 0, "item_count": 1, "structure": "table"},
            {"heading": "Total Current Liabilities", "page": 0, "item_count": 1, "structure": "table"},
        ],
    }],
}


def _rows_json(pairs, start_row=1):
    return [{"label_col": "A", "value_col": "B", "row": i + start_row,
             "label": l, "value": v} for i, (l, v) in enumerate(pairs)]


def _mock_llm_response(prompt: str):
    """Dispatch on the real prompts' stable prefixes; return the documented
    model answers. Section heading is parsed out of the Layer-2 prompt."""
    from connectors.groq_client import LLMResponse

    def resp(payload):
        return LLMResponse(raw_text=json.dumps(payload), parsed_json=payload,
                           model_used="mock-replay-of-audit-2026-08-17",
                           tokens_used=0, success=True)

    if prompt.startswith("Analyze this entire document"):
        return resp(L1_DOCUMENT_MAP)

    import re
    m = re.search(r"Extract (?:the|ALL content from the) '([^']+)' section", prompt)
    heading = m.group(1) if m else ""

    if heading == "Current Assets":
        return resp({"layout_sections": {"currentassets": {"rows": _rows_json(ASSET_ROWS)}},
                     "extracted_fields": {"B10": "415000"}})
    if heading == "Current Liabilities":
        return resp({"layout_sections": {"currentliabilities": {"rows": _rows_json(LIAB_ROWS)}},
                     "extracted_fields": {"D10": "400000"}})
    if heading == "Total Current Assets":
        # asked for a "section" that is really the totals row, the model
        # returns the whole assets column: 4 items + the total (5 rows)
        return resp({"layout_sections": {"totalcurrentassets": {
            "rows": _rows_json(ASSET_ROWS + [("Total Current Assets", "415000")])}}})
    if heading == "Total Current Liabilities":
        return resp({"layout_sections": {"totalcurrentliabilities": {
            "rows": _rows_json(LIAB_ROWS + [("Total Current Liab.", "400000")])}}})

    return LLMResponse(raw_text="", success=False,
                       error=f"mock has no answer for prompt: {prompt[:120]}")


@pytest.fixture()
def audited_llm(monkeypatch):
    from connectors.llm_router import LLMRouter

    def extract(self, text="", image_b64="", prompt="", system_instruction="",
                model=None):
        return _mock_llm_response(prompt)

    monkeypatch.setattr(LLMRouter, "extract", extract)
    yield


def _run_structural_pipeline():
    from app.api.routes.extract import _extract_with_template, _parse_template
    from app.models.models import ColumnTemplate
    from orchestrator import Orchestrator
    from tests.harness.runner import _schema_path

    grid = json.loads(FIXTURE_TEMPLATE.read_text(encoding="utf-8"))
    tpl = ColumnTemplate(name="bs_unlabeled", document_type="balance_sheet",
                         description=json.dumps(grid), columns_json="[]")
    template_data = _parse_template(tpl)

    log = io.StringIO()
    with contextlib.redirect_stdout(log):
        orchestrator = Orchestrator(client_schema_path=_schema_path())
        results = _extract_with_template(orchestrator, FIXTURE_PDF, template_data)
    return results, grid, log.getvalue()


def _export_excel(results, grid):
    """Export exactly as GET /api/jobs/{id}/export does: rebuild from the
    persisted extraction_json, preferring its stored template_regions."""
    import openpyxl
    from app.api.routes.extract import _analyse_template_regions, _write_excel
    from app.models.models import DocumentResult

    docs = []
    regions = None
    for r in results:
        ed = getattr(r, "extracted_data", None) or {}
        regions = regions or ed.get("template_regions")
        docs.append(DocumentResult(
            filename=getattr(r, "filename", "BalanceSheet-synth.pdf"),
            document_type=getattr(r, "document_type", "") or "balance_sheet",
            extraction_json=json.dumps(ed, default=str),
        ))
    regions = regions or _analyse_template_regions(grid)
    wb = openpyxl.Workbook()
    ws = wb.active
    with contextlib.redirect_stdout(io.StringIO()):
        _write_excel(ws, docs, grid, regions, openpyxl)
    return ws


class TestP3FabricatedLineItem:
    def test_no_fabricated_duplicate_row_in_export(self, audited_llm):
        results, grid, log = _run_structural_pipeline()

        # Guard: the intended path must actually have run — the v4 structural
        # three-layer engine with the audited 4-section document map. If this
        # guard fails the test failed for the wrong reason.
        assert "-> layout extraction" in log, log
        assert "document map: 1 documents, 4 total sections" in log, log
        assert "falling back to legacy" not in log, log
        assert results and getattr(results[0], "success", False), (
            getattr(results[0], "error_message", "no results"))

        ws = _export_excel(results, grid)

        rows = []  # every (label, value) line written to the asset columns
        for row in ws.iter_rows(min_row=2):  # row 1 = section headers
            label, value = row[0].value, row[1].value
            if label is not None and str(label).strip():
                rows.append((str(label).strip(), value))

        labels = [l for l, _ in rows]
        duplicates = sorted({l for l in labels if labels.count(l) > 1})
        source_labels = [l for l, _ in ASSET_ROWS] + ["Total Current Assets"]

        assert duplicates == [], (
            f"Fabricated duplicate line item(s) in the exported sheet: "
            f"{duplicates}. The source document lists each asset exactly "
            f"once ({source_labels}); the export wrote: {labels}. "
            f"This is audit finding P3 (S5 truncation keeps a phantom "
            f"section's first LINE ITEM; _match_group merges it into the "
            f"real section; both dedup guards miss the subset)."
        )
