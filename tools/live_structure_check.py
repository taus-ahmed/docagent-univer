"""Run T2, Stage 7: the new path against the REAL model, under a hard $1 cap.

    backend\\.venv\\Scripts\\python.exe tools\\live_structure_check.py              # offline: plan + commands
    backend\\.venv\\Scripts\\python.exe tools\\live_structure_check.py --live --set vendor
    backend\\.venv\\Scripts\\python.exe tools\\live_structure_check.py --live --set expense
    backend\\.venv\\Scripts\\python.exe tools\\live_structure_check.py --live --set compare

OFFLINE BY DEFAULT: without --live it makes NO call and prints the plan and
the exact PowerShell commands to run it. With --live it needs
GEMINI_API_KEY in THIS shell's environment (it never reads .env:
DOCAGENT_TEST_NO_DOTENV is set) - type the key with Read-Host in your own
session; this tool never prints, logs or stores it.

THE CAP IS HARD AND SHARED. Every model call goes through one wrapper on
`LLMRouter.extract` (the project's single chokepoint, the same one the
harness cache wraps), which:
  * BEFORE the call refuses it when (spent so far + this call's WORST case)
    would pass the cap - worst case = the estimated input tokens plus the
    model's whole output allowance, at the model's list price;
  * AFTER the call adds the priced attempts (every retry; thinking billed as
    output) to a ledger kept in local_docs/live_structure/ledger.json, so the
    $1 is the total over ALL runs, not per run (`--reset-ledger` starts a new
    budget, and says so);
  * writes one JSON line per call to local_docs/live_structure/calls.jsonl:
    set, document, section, model requested/answered, input / output /
    thinking tokens, cost, retries (attempts), finish reason, and the chunk
    sizes (prompt and text characters, page images, estimated input tokens).
A refused call is a FAILED call for the pipeline (it says so), never an
empty answer.

SETS
  vendor   the 8-page vendor list (local_docs/DocAgent_testdocs/invoice/
           mobile_vendor_list_8pg.pdf): Regular no-template extraction through
           the sized calls (engine/call_sizing), then structure PLANS from the
           model for each page; the Organized layout from those plans vs the
           geometry's.
  expense  re-records the no-template harness answer for EXP-2024-0081 (the
           recording missing since Run T, so `--no-template` replay stops on a
           CacheMiss) - `tests.harness.runner --mode record --no-template
           --docs EXP-2024-0081`, inside the same cap.
  compare  20 documents: old Organized (no model), new structure engine (model
           plans) and Regular no-template extraction (model), compared value
           by value: every value Regular extracted, and where (if anywhere)
           each layout put it and under which header. Per document and summed,
           to local_docs/live_structure/compare.json and compare.xlsx.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "local_docs" / "live_structure"
DOCS = ROOT / "local_docs" / "DocAgent_testdocs"
CAP_USD = 1.00

VENDOR = "invoice/mobile_vendor_list_8pg.pdf"
EXPENSE_DOC = "EXP-2024-0081"
COMPARE = [
    # the 11 keyed documents (Run T2 Stage 1) ...
    "bank_statement/carson_bank_6pg.pdf", "bank_statement/mammoth_2pg.pdf",
    "bank_statement/flowparse_bank_us.pdf", "invoice/flowparse_invoice_tax.pdf",
    "receipt_pdf/flowparse_cafe.pdf", "payslip/utah_paystub_2.pdf",
    "w2/irs6744_w2_mcguire.pdf", "1099/irs6744_1099NEC_1099K_garcia.pdf",
    "payslip/unm_paystub.pdf", "bank_statement/boa_how_to_read.pdf",
    "1099/irs_1099nec_ellis.pdf",
    # ... and nine more shapes: a long list, a brokerage statement, a merchant
    # statement, a neobank, a scanned-and-OCR'd invoice, a garbled pay stub,
    # two widget forms, a multi-page purchase order
    VENDOR, "bank_statement/fidelity_brokerage.pdf", "bank_statement/fiserv_merchant_5pg.pdf",
    "bank_statement/flowparse_neobank.pdf", "scans_made/scan_ccsu_invoice.pdf",
    "payslip/utep_paystub.pdf", "w2/irs_w2_2012.pdf", "1099/irs_1099int_mod3.pdf",
    "purchase_order/gallatin_po_4pg.pdf",
]
# long_digital_25pg is left out: 25 pages of plans would take a large share of
# the $1 by itself, and its pages are in the set already (carson, vendor list)


def commands() -> str:
    return r"""
# PowerShell, in your own session (Windows PowerShell 5.1 or 7). The key is
# typed, never echoed, kept only in this shell's environment, removed after.
cd E:\docagent-integration
$s = Read-Host "Gemini API key" -AsSecureString
$env:GEMINI_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
$env:DOCAGENT_TEST_NO_DOTENV = "1"
$env:GEMINI_MODEL = "gemini-2.5-flash-lite"   # what production runs
$env:PYTHONIOENCODING = "utf-8"

# 1. the 8-page vendor list: sized extraction + structure plans
backend\.venv\Scripts\python.exe tools\live_structure_check.py --live --set vendor

# 2. the expense report's missing no-template recording, then the harness
backend\.venv\Scripts\python.exe tools\live_structure_check.py --live --set expense
backend\.venv\Scripts\python.exe -m tests.harness.runner --mode replay --no-template

# 3. 20 documents: old Organized vs new engine vs Regular, cell by cell
backend\.venv\Scripts\python.exe tools\live_structure_check.py --live --set compare

# what was spent, per call
Get-Content local_docs\live_structure\ledger.json
Remove-Item Env:GEMINI_API_KEY
"""


# ── the cap ──────────────────────────────────────────────────────────────────

class Ledger:
    def __init__(self, path: Path, cap: float):
        self.path, self.cap = path, cap
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        self.spent = float(data.get("spent_usd", 0.0))
        self.calls = int(data.get("calls", 0))
        self.refused = int(data.get("refused", 0))

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"cap_usd": self.cap, "spent_usd": round(self.spent, 6),
                                         "calls": self.calls, "refused": self.refused,
                                         "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                                  time.gmtime())}, indent=1),
                             encoding="utf-8")


def worst_case_usd(kw, model) -> tuple:
    """This call's most it can cost: estimated input tokens (characters / 4,
    plus ~258 per page image) and the model's whole output allowance."""
    import call_sizing as CS
    import llm_contract as LC
    chars = sum(len(str(kw.get(k) or "")) for k in ("text", "prompt", "system_instruction"))
    imgs = kw.get("image_b64")
    n_img = len(imgs) if isinstance(imgs, list) else (1 if imgs else 0)
    inp = chars / 4 + 258 * n_img
    out = int(kw.get("max_output_tokens") or CS.output_limit(model))
    p = LC.price_for(model) or {"input": 1.50, "output": 10.00}     # unknown: assume dear
    return inp / 1e6 * p["input"] + out / 1e6 * p["output"], int(inp), chars, n_img


CONTEXT = {"set": "", "doc": ""}


def install_cap(ledger: Ledger, log_path: Path):
    """Wrap LLMRouter.extract (and classify) with the cap and the call log."""
    from connectors.base import LLMResponse
    from connectors.llm_router import LLMRouter
    import llm_contract as LC
    orig_extract, orig_classify = LLMRouter.extract, LLMRouter.classify
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def refuse(why):
        ledger.refused += 1
        ledger.save()
        print(f"[CAP] refused: {why}", flush=True)
        return LLMResponse(raw_text="", success=False, error=f"live_structure_check cap: {why}",
                           error_kind="cap")

    def capped(fn, kind):
        def run(self, *a, **kw):
            model = kw.get("model") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash"
            worst, inp, chars, n_img = worst_case_usd(kw, model)
            if ledger.spent + worst > ledger.cap:
                return refuse(f"${ledger.spent:.4f} spent; this call could cost up to "
                              f"${worst:.4f}; cap ${ledger.cap:.2f}")
            t0 = time.time()
            r = fn(self, *a, **kw)
            atts = [x for x in getattr(r, "attempts", None) or [] if isinstance(x, dict)]
            cost = sum(float(x["cost_estimate"]) for x in atts
                       if x.get("cost_estimate") is not None)
            if atts and all(x.get("cost_estimate") is None for x in atts):
                cost = worst                         # unpriced: count the worst case
            ledger.spent += cost
            ledger.calls += 1
            ledger.save()
            rec = {"set": CONTEXT["set"], "doc": CONTEXT["doc"], "kind": kind,
                   "section": (atts[-1].get("section") if atts else "") or "",
                   "model_requested": model, "model_answered": getattr(r, "model_used", ""),
                   "input_tokens": sum(int(x.get("prompt_tokens") or 0) for x in atts),
                   "output_tokens": sum(int(x.get("output_tokens") or 0) for x in atts),
                   "thinking_tokens": sum(int(x.get("thinking_tokens") or 0) for x in atts),
                   "cost_usd": round(cost, 6), "attempts": len(atts),
                   "retries": max(0, len(atts) - 1),
                   "finish_reason": getattr(r, "finish_reason", None),
                   "success": bool(getattr(r, "success", False)),
                   "chunk": {"prompt_chars": chars, "images": n_img,
                             "est_input_tokens": inp,
                             "max_output_tokens": kw.get("max_output_tokens")},
                   "seconds": round(time.time() - t0, 2),
                   "spent_total_usd": round(ledger.spent, 6)}
            with log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
            print(f"[CALL] {rec['set']}/{rec['doc']} {rec['section'] or kind}: {rec['model_answered']} "
                  f"in {rec['input_tokens']} out {rec['output_tokens']} think "
                  f"{rec['thinking_tokens']} ${rec['cost_usd']:.4f} retries {rec['retries']} "
                  f"(total ${ledger.spent:.4f} of ${ledger.cap:.2f})", flush=True)
            return r
        return run
    LLMRouter.extract = capped(orig_extract, "extract")
    LLMRouter.classify = capped(orig_classify, "classify")
    _ = LC


# ── the sets ─────────────────────────────────────────────────────────────────

def _router():
    from connectors.llm_router import LLMRouter
    return LLMRouter()


def regular(path):
    """Regular no-template extraction of one file: [extracted_data]."""
    from extractor import run_extraction
    llm = _router()
    return [r.extracted_data or {} for r in run_extraction(SimpleNamespace(llm=llm), path, None,
                                                          batch_schemas={})]


def structure(path, model):
    """The structure layout with MODEL plans, and the geometry's layout."""
    import perception as P
    import structure_engine as S
    from app.services import perception_store as PS
    perc = P.read_document(path, ocr=True)
    geo = S.layout_document(perc)
    PS.plan_pages(perc, SimpleNamespace(llm=_router()), path, model=model)
    return S.layout_document(perc, plans=S.stored_plans(perc)), geo, perc


def run_vendor(model):
    p = DOCS / VENDOR
    CONTEXT.update(set="vendor", doc=p.name)
    data = regular(p)
    rows = sum(len(v) for d in data for k, v in d.items() if k.endswith("_rows")
               and isinstance(v, list))
    strat = [d.get("diagnostics", {}).get("call_strategy") for d in data]
    new, geo, _perc = structure(p, model)
    out = {"file": VENDOR, "regular_records": len(data), "regular_table_rows": rows,
           "call_strategy": strat, "plan_source": new["plan_source"],
           "flags_model_plans": new["flags"][:30], "flags_geometry": geo["flags"][:30],
           "cells_model": sum(len(c) for c in new["pages"]),
           "cells_geometry": sum(len(c) for c in geo["pages"])}
    (OUT / "vendor.json").write_text(json.dumps(out, indent=1, default=str), encoding="utf-8")
    print(json.dumps(out, indent=1, default=str)[:3000])


def run_expense():
    CONTEXT.update(set="expense", doc=EXPENSE_DOC)
    sys.path.insert(0, str(ROOT))
    from tests.harness import runner
    argv = sys.argv
    try:
        sys.argv = ["runner", "--mode", "record", "--no-template", "--docs", EXPENSE_DOC]
        runner.main()
    finally:
        sys.argv = argv


def _values(data) -> list:
    """(value, where) for every value Regular extracted: fields by label,
    table cells by column."""
    out = []
    for d in data:
        for lab, rec in (d.get("extracted_data") or {}).items():
            v = rec.get("value") if isinstance(rec, dict) else rec
            if v not in (None, ""):
                out.append((str(v), f"field: {lab}"))
        for k, rows in d.items():
            if k.endswith("_rows") and isinstance(rows, list):
                for row in rows:
                    for col, v in (row or {}).items():
                        if not str(col).startswith("_") and v not in (None, ""):
                            out.append((str(v), f"{k[:-5]}: {col}"))
    return out


def _cells(lay) -> dict:
    """normalised text -> [(block, A1, header above)] for a layout."""
    from openpyxl.utils import get_column_letter
    import re as _re
    out = {}
    for bi, cells in enumerate(lay.get("pages") or []):
        heads = {}
        for c in sorted(cells, key=lambda c: (c["row"], c["col"])):
            t = str(c.get("text") if c.get("text") is not None else c.get("value"))
            if c.get("kind") == "header" or c.get("header"):
                heads[c["col"]] = t
            key = _re.sub(r"\s+", " ", t).strip().casefold()
            out.setdefault(key, []).append((bi + 1, f"{get_column_letter(c['col'] + 1)}{c['row'] + 1}",
                                            heads.get(c["col"], "")))
    return out


def run_compare(model):
    import re as _re
    import organized_layout as OL
    rows, summary = [], []
    for rel in COMPARE:
        p = DOCS / rel
        if not p.exists():
            summary.append({"file": rel, "error": "not present"})
            continue
        CONTEXT.update(set="compare", doc=p.name)
        try:
            old = OL.layout(p)
            new, _geo, _perc = structure(p, model)
            data = regular(p)
        except Exception as e:                               # one document, never the run
            summary.append({"file": rel, "error": f"{type(e).__name__}: {e}"[:200]})
            continue
        oc, nc = _cells(old), _cells(new)
        vals = _values(data)
        s = {"file": rel, "values": len(vals), "in_old": 0, "in_new": 0, "in_both": 0,
             "in_neither": 0}
        for v, where in vals:
            key = _re.sub(r"\s+", " ", v).strip().casefold()
            o, n = oc.get(key, []), nc.get(key, [])
            s["in_old"] += bool(o)
            s["in_new"] += bool(n)
            s["in_both"] += bool(o and n)
            s["in_neither"] += not (o or n)
            rows.append([rel, v, where, "; ".join(f"b{b}!{a} [{h}]" for b, a, h in o[:3]),
                         "; ".join(f"b{b}!{a} [{h}]" for b, a, h in n[:3])])
        summary.append(s)
        print(f"{rel}: {s}", flush=True)
    (OUT / "compare.json").write_text(json.dumps({"summary": summary, "rows": rows}, indent=1),
                                      encoding="utf-8")
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "values"
    ws.append(["file", "Regular value", "Regular field/column", "old Organized cell [header]",
               "new engine cell [header]"])
    for r in rows:
        ws.append(r)
    ws2 = wb.create_sheet("summary")
    keys = ["file", "values", "in_old", "in_new", "in_both", "in_neither", "error"]
    ws2.append(keys)
    for s in summary:
        ws2.append([s.get(k) for k in keys])
    wb.save(OUT / "compare.xlsx")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--live", action="store_true", help="make real model calls (costs money)")
    ap.add_argument("--set", choices=["vendor", "expense", "compare", "all"], default="all")
    ap.add_argument("--reset-ledger", action="store_true",
                    help="start a NEW $1 budget (the old ledger is kept beside it)")
    a = ap.parse_args(argv)
    present = [r for r in COMPARE if (DOCS / r).exists()]
    print(f"vendor list: {VENDOR} ({'present' if (DOCS / VENDOR).exists() else 'MISSING'})")
    print(f"expense report: tests/test_pdfs/{EXPENSE_DOC}.pdf (harness no-template re-record)")
    print(f"compare set: {len(COMPARE)} documents, {len(present)} present")
    ledger = Ledger(OUT / "ledger.json", CAP_USD)
    print(f"ledger: ${ledger.spent:.4f} of ${CAP_USD:.2f} spent over {ledger.calls} call(s)")
    if not a.live:
        print("offline: no calls made. To run it:")
        print(commands())
        return 0
    if not os.environ.get("GEMINI_API_KEY"):
        print("--live needs GEMINI_API_KEY in this shell's environment (see the commands).",
              file=sys.stderr)
        return 2
    os.environ["DOCAGENT_TEST_NO_DOTENV"] = "1"
    for p in (ROOT / "backend" / "engine", ROOT / "backend", ROOT):
        sys.path.insert(0, str(p))
    from tests.harness.bootstrap import bootstrap, chdir_backend
    bootstrap()
    chdir_backend()
    if a.reset_ledger and (OUT / "ledger.json").exists():
        old = OUT / f"ledger_{time.strftime('%Y%m%d_%H%M%S')}.json"
        (OUT / "ledger.json").rename(old)
        print(f"ledger reset; the old one is {old.name}")
        ledger = Ledger(OUT / "ledger.json", CAP_USD)
    if ledger.spent >= CAP_USD:
        print(f"the ${CAP_USD:.2f} budget is spent (${ledger.spent:.4f}); nothing run.")
        return 3
    install_cap(ledger, OUT / "calls.jsonl")
    model = os.environ.get("GEMINI_MODEL") or None
    if a.set in ("vendor", "all"):
        run_vendor(model)
    if a.set in ("expense", "all"):
        run_expense()
    if a.set in ("compare", "all"):
        run_compare(model)
    print(f"done: ${ledger.spent:.4f} of ${CAP_USD:.2f} spent, {ledger.calls} call(s), "
          f"{ledger.refused} refused by the cap")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.exit(main())
