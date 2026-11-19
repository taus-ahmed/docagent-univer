"""Run B - B2 (meaning), B3 (format rules), B4 (value grounding, watermark),
B8 (the template-columns flag). Offline; every model answer is scripted or a
committed recorded answer (tests/fixtures/run_b/*.raw.json, captured live in
B0 under the hard call cap)."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.contract import run_a_driver as D  # bootstraps sys.path

import aliases as AL  # noqa: E402
import format_rules as FR  # noqa: E402
import llm_contract as C  # noqa: E402
from connectors.base import LLMResponse  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "tests" / "fixtures" / "acceptance" / "source_docs"
RUN_B = ROOT / "tests" / "fixtures" / "run_b"

CARD_CATEGORIES = ["Payment", "Dining", "Groceries", "Travel", "Fuel", "Subscriptions",
                   "Office", "Groceries", "Lodging", "Dining", "Electronics", "Fuel",
                   "Insurance"]


def _replay(rel, sheet, doc_type, answer, grid=None):
    from core.preprocessor import preprocess_file
    from slot_extractor import run_slot_extraction

    doc = preprocess_file(DOCS / rel)

    def extract(**kw):
        return LLMResponse(raw_text=json.dumps(answer), parsed_json=json.loads(json.dumps(answer)),
                           success=True, model_used="offline-recorded")

    n = len(doc.page_texts)
    with C.collect_attempts(fresh=True):
        return run_slot_extraction(
            SimpleNamespace(llm=SimpleNamespace(extract=extract)), DOCS / rel,
            {"layout": grid or D.template_grid(sheet)}, None, page_images=[],
            doc_text=doc.extracted_text, doc_text_pages=doc.page_texts,
            file_type="digital_pdf", default_doc_type=doc_type, start=0.0,
            page_lines=doc.page_lines,
            page_origins={i + 1: o for i, o in enumerate(doc.page_origins)},
            page_numbers=list(range(1, n + 1)), widget_values=doc.widget_values,
            form_fields=doc.form_fields)[0].extracted_data


def _recorded(name):
    return json.loads(json.loads((RUN_B / name).read_text(encoding="utf-8"))[0])


def _rows(data):
    return data.get("table_rows") or next(v for k, v in data.items()
                                          if k.endswith("_rows") and v)


# ── B4: watermark ────────────────────────────────────────────────────────────

def test_the_sample_watermark_never_reaches_the_text_or_the_words():
    from core.preprocessor import preprocess_file
    doc = preprocess_file(DOCS / "credit_card" / "flowparse_card_us.pdf")
    text = doc.page_texts[0]
    for leaked in ("ETravel", "M Subscriptions", "A Office"):
        assert leaked not in text
    assert "SKYLARK AIR TICKETS Travel $412.00" in text
    lone = [ln for ln in doc.page_lines[0] if len(ln) == 1 and ln[0]["text"] in "SAMPLE"]
    assert lone == []


def test_card_categories_are_exact_and_unflagged():
    data = _replay("credit_card/flowparse_card_us.pdf", "Card_Stmt",
                   "credit_card_statement", _recorded("card_live_b0.raw.json"))
    assert [r["Category"] for r in _rows(data)] == CARD_CATEGORIES
    assert data["validation"]["flagged_fields"] == []
    assert data["extracted_data"]["Card Last 4"]["value"] == "7421"


def test_a_page_without_a_watermark_reads_byte_identically():
    import pdfplumber
    from text_layer import read_page
    with pdfplumber.open(DOCS / "w2" / "irs_w2_2012.pdf") as pdf:
        page = pdf.pages[0]
        assert read_page(page)[0] == page.extract_text()


# ── B4: value-based grounding ────────────────────────────────────────────────

def test_a_row_whose_quote_is_not_on_the_page_is_anchored_by_its_values():
    """The recorded answer quotes lines WITH the watermark letters in them;
    the clean text no longer holds those quotes, but every value is printed
    on one line, and that line becomes the row's source."""
    answer = _recorded("card_live_b0.raw.json")
    quoted = [r["source"] for r in answer["tables"]["table"]]
    assert any("ETravel" in q for q in quoted)
    data = _replay("credit_card/flowparse_card_us.pdf", "Card_Stmt",
                   "credit_card_statement", answer)
    travel = next(r for r in _rows(data) if r["Category"] == "Travel")
    assert "ETravel" not in travel["_source"] and "_ungrounded" not in travel
    assert data["validation"]["reanchored_count"] >= 3


def test_a_value_printed_nowhere_is_still_ungrounded():
    from slot_extractor import enumerate_slots
    ids = {f["row_label"]: f["slot_id"]
           for f in enumerate_slots(D.template_grid("Card_Stmt"))["fields"]}
    answer = {"fields": {ids["New Balance"]: {"value": "$9,999.99",
                                              "source": "New balance $9,999.99", "page": 1}},
              "tables": {}}
    data = _replay("credit_card/flowparse_card_us.pdf", "Card_Stmt",
                   "credit_card_statement", answer)
    assert data["field_provenance"]
    assert any(f["ref"] == "New Balance" for f in data["validation"]["flagged_fields"])


# ── B3: last 4 and type checks ───────────────────────────────────────────────

def test_job15_last_4_is_machine_corrected_from_the_printed_account_number():
    data = D.replay_job(15)["extracted_data"]
    assert data["extracted_data"]["Account Number Last 4"]["value"] == "8842"
    prov = next(p for p in data["field_provenance"].values() if p.get("machine_corrected"))
    assert prov["machine_corrected"] == "58842"
    assert not any(f["ref"] == "Account Number Last 4"
                   for f in data["validation"]["flagged_fields"])


def test_last_4_rules():
    lines = D.words(1, ["Routing 071000505 · Account 7301558842", "Card ending 7421"])
    assert FR.check_last4("8842", lines)[:2] == ("ambiguous", "8842") or \
        FR.check_last4("8842", lines)[0] == "ok"
    assert FR.check_last4("8842", lines)[0] == "ok"
    assert FR.check_last4("7421", lines)[0] == "ok"
    assert FR.check_last4("1234", lines)[0] == "ambiguous"       # two numbers printed
    one = D.words(1, ["Account number 7301558842"])
    assert FR.check_last4("58842", one) == ("corrected", "8842", "Account number 7301558842")
    assert FR.check_last4("8842", D.words(1, ["no number here"]))[0] == "none"
    masked = D.words(1, ["Account: XXXX-0000"])
    assert FR.check_last4("0000", masked)[0] == "ok"


@pytest.mark.parametrize("value,label,ok,norm", [
    ("$1,284.37", "Previous Balance", True, "1284.37"),
    ("0.00", "Fees Charged", True, "0.00"),
    ("N/A", "Interest Charged", False, None),
    ("09/16/2026", "Payment Due Date", True, "2026-09-16"),
    ("pending", "Payment Due Date", False, None),
    ("36-8XXXXXXX", "Lender TIN", True, None),
    ("10111", "Employer ZIP", True, None),
    ("Business Checking", "Account Type", True, None),
])
def test_type_checks_flag_never_coerce(value, label, ok, norm):
    assert FR.check_type(value, label)[:2] == (ok, norm)


# ── B2: match by meaning ─────────────────────────────────────────────────────

def test_aliases_are_small_generic_and_declared_ones_come_first():
    assert "delivered to" in AL.aliases_for("Ship To")
    assert "ship to" in AL.aliases_for("Sent To")
    assert "balance" in AL.aliases_for("Running Balance")
    assert "description" in AL.aliases_for("Item Description")
    assert AL.aliases_for("Total Credits") == []         # a total is not its column
    grid = {"cells": {"0,0": {"value": "Deliver Here", "aliases": ["Ship To"]}}}
    assert AL.cell_aliases(grid, 0, 0) == ["Ship To"]
    assert AL.cell_aliases({"cells": {"0,0": {"value": "x"}}}, 0, 0) == []


def test_the_prompt_names_the_documents_wording_only_where_it_differs():
    grid = {"cells": {"0,0": {"value": "Delivered To"}, "1,0": {"value": "Invoice Date"}},
            "merges": {}, "colWidths": [], "repeatRows": []}
    prompts = []

    def extract(**kw):
        prompts.append(kw.get("prompt", ""))
        return D.model_response({"fields": {}, "tables": {}})

    D.run_synthetic(extract, [["Ship To: Acme Ltd, 1 Main St", "Invoice Date 01/02/2026"]],
                    grid=grid)
    assert 'F1 "Delivered To": the document may say "ship to"' in prompts[0]
    assert "Match every slot by MEANING" in prompts[0]
    assert '"Invoice Date": the document may say' not in prompts[0]

    prompts.clear()
    same = {"cells": {"0,0": {"value": "Ship To"}}, "merges": {}, "colWidths": [],
            "repeatRows": []}
    D.run_synthetic(extract, [["Ship To: Acme Ltd"]], grid=same)
    assert "WORDING" not in prompts[0]


def test_label_wording_diagnostics_are_information_only():
    data = D.replay_job(19)["extracted_data"]
    diag = data["validation"]["label_wording"]
    assert "Item Description" in diag["no_literal_match"]
    assert "Item Description" in diag["printed_by_alias"]
    assert data["validation"]["flagged_fields"] == []


# ── B8: the template-columns flag still fires when it should ─────────────────

def test_template_columns_flag_fires_for_a_filled_column_the_document_never_names():
    grid = {"cells": {"0,0": {"value": "Date"}, "0,1": {"value": "Description"},
                      "0,2": {"value": "Variance"}},
            "merges": {}, "colWidths": [], "repeatRows": []}
    from slot_extractor import enumerate_slots
    t = enumerate_slots(grid)["tables"][0]
    answer = {"fields": {}, "tables": {t["name"]: [
        {"cells": {"Date": "01/01", "Description": "ITEM-A", "Variance": "40.00"},
         "source": "01/01 ITEM-A 40.00", "page": 1}]}}
    data = D.run_synthetic(lambda **kw: D.model_response(json.loads(json.dumps(answer))),
                           [["DATE DESCRIPTION AMOUNT", "01/01 ITEM-A 40.00"]], grid=grid)
    flags = [f for f in data["validation"]["flagged_fields"] if f["ref"] == "template columns"]
    assert flags and "'Variance'" in flags[0]["value"]


def test_template_columns_flag_is_silent_for_an_empty_or_reworded_column():
    for job in (15, 19, 21):
        flags = D.replay_job(job)["extracted_data"]["validation"]["flagged_fields"]
        assert not [f for f in flags if f["ref"] == "template columns"], job


# ── opening-balance line in a transaction table ──────────────────────────────

def test_bank_beginning_balance_line_is_not_a_transaction():
    data = _replay("bank_statement/flowparse_bank_us.pdf", "Bank_Recon", "bank_statement",
                   _recorded("bank_live_b0.raw.json"))
    rows = _rows(data)
    assert len(rows) == 12
    assert "BEGINNING BALANCE" not in {r["Description"] for r in rows}
    assert data["validation"]["opening_row_count"] == 1
    assert data["extracted_data"]["Opening Balance"]["value"] == "$18,240.12"
    # an "Ending Balance" is money, never an account suffix (B2.3 live finding)
    assert data["extracted_data"]["Listed Ending Balance"]["value"] == "20,376.00"
    assert data["extracted_data"]["Closing Balance"]["value"] == "$20,376.00"
    assert data["validation"]["flagged_fields"] == []


@pytest.mark.parametrize("label,is_last4", [
    ("Account Number Last 4", True), ("Card Last 4", True), ("Account Ending", True),
    ("Card ending in", True), ("Acct last digits", True), ("Ending Balance", False),
    ("Listed Ending Balance", False), ("Period Ending", False), ("Closing Balance", False)])
def test_only_a_last_4_label_is_a_last_4_slot(label, is_last4):
    assert FR.is_last4_slot(label) is is_last4
