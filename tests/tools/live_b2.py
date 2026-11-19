"""Run B, B2.3: reworded-label variants, live, through tests.tools.live_cap.

    python -m tests.tools.live_b2 --state <scratch>/live_state.json --out <dir>

Two variants each of the invoice and bank templates: A uses ordinary
synonyms, B the owner's own words. Reports, per original slot, the value the
reworded template got, so the variants can be compared with each other and
with the golden values. Each variant is one engine run (normally one call).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

os.environ["DOCAGENT_TEST_NO_DOTENV"] = "1"

from tests.tools import live_b0  # noqa: E402  (bootstraps, cap helpers)
from tests.tools import live_cap  # noqa: E402
from tests.contract.run_a_driver import template_grid  # noqa: E402

VARIANTS = {
    "inv_A": ("AP_Inv_Full", {
        "Vendor Name": "Supplier", "Invoice Number": "Invoice No",
        "Invoice Date": "Date of Invoice", "Due Date": "Pay By",
        "Bill To Name": "Sold To", "Ship To Address": "Delivered To",
        "Payment Terms": "Terms", "Description": "Details", "Quantity": "Qty",
        "Unit Price": "Rate", "Line Amount": "Extended"}),
    "inv_B": ("AP_Inv_Full", {
        "Vendor Name": "Who billed us", "Invoice Number": "Their reference",
        "Invoice Date": "Billed on", "Due Date": "Must pay by",
        "Bill To Name": "Our company", "Currency": "Money type",
        "Description": "What we bought", "Quantity": "How many",
        "Unit Price": "Each", "Line Amount": "Line cost"}),
    "bank_A": ("Bank_Recon", {
        "Opening Balance": "Beginning Balance", "Closing Balance": "Ending Balance",
        "Account Holder": "Customer", "Account Number Last 4": "Account Ending",
        "Withdrawal": "Debits", "Deposit": "Credits", "Running Balance": "Balance",
        "Description": "Details"}),
    "bank_B": ("Bank_Recon", {
        "Bank Name": "Institution", "Opening Balance": "Money at start",
        "Closing Balance": "Money at end", "Total Deposits and Credits": "All money in",
        "Total Withdrawals and Debits": "All money out",
        "Account Number Last 4": "Acct last digits", "Withdrawal": "Money out",
        "Deposit": "Money in", "Running Balance": "Left over"}),
}
CASE = {"AP_Inv_Full": ("invoice/flowparse_invoice_tax.pdf", "invoice"),
        "Bank_Recon": ("bank_statement/flowparse_bank_us.pdf", "bank_statement")}


def reworded(sheet, mapping):
    g = template_grid(sheet)
    for cell in g["cells"].values():
        if cell.get("value") in mapping:
            cell["value"] = mapping[cell["value"]]
    return g


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--variant", action="append")
    a = ap.parse_args(argv)
    if not os.environ.get("GEMINI_API_KEY"):
        print("GEMINI_API_KEY not set: not measured")
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    live_cap.install(a.state)
    import llm_contract as C
    from connectors.llm_router import LLMRouter
    from extractor import run_extraction
    from types import SimpleNamespace
    for name in a.variant or list(VARIANTS):
        sheet, mapping = VARIANTS[name]
        rel, dt = CASE[sheet]
        live_cap.set_label(name)
        back = {v: k for k, v in mapping.items()}
        try:
            with C.collect_attempts(fresh=True):
                res = run_extraction(SimpleNamespace(llm=LLMRouter()),
                                     live_b0.DOCS / rel,
                                     {"layout": reworded(sheet, mapping), "doc_type": dt})
        except live_cap.CapReached:
            print(f"{name}: cap reached, stopped")
            break
        ed = res[0].extracted_data
        fields = {back.get(k, k): (v or {}).get("value") for k, v in
                  (ed.get("extracted_data") or {}).items()}
        rows = ed.get("table_rows") or []
        rows = [{back.get(k, k): v for k, v in r.items() if not k.startswith("_")}
                for r in rows]
        rep = {"variant": name, "fields": fields, "rows": rows,
               "filled": sum(1 for v in fields.values() if str(v or "").strip()),
               "slots": len(fields), "row_count": len(rows),
               "flags": (ed.get("validation") or {}).get("flagged_fields"),
               "state": ed.get("document_state"),
               "wording": (ed.get("validation") or {}).get("label_wording")}
        (a.out / f"{name}.json").write_text(json.dumps(rep, indent=1, default=str),
                                            encoding="utf-8")
        print(json.dumps({k: rep[k] for k in ("variant", "filled", "slots", "row_count",
                                               "state")}), flush=True)
    live_cap.summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
