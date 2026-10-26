"""Several documents in one file, generated (Part 3.3).

    python tests/fixtures/make_multidoc_fixtures.py --out <dir>

Equivalents of the shapes real stacks arrive in, built from the locale
fixtures' documents so their truth is known; nothing here is a real document.

  invoices_3            three invoices, three invoice numbers
  statements_2_accounts two statements of different accounts
  statements_2_months   two months of ONE account (same number, same title)
  invoices_blank_sep    two invoices with a blank separator page between
  claim_packet          an estimate, the cheque paying it and a release, all
                        quoting one claim number
  invoices_unnumbered   two invoices whose pages carry no reference at all

`expect`: the page indices that start a document, and whether the file must
be flagged `possible_multiple_documents` (the count could not be
established — never split on a guess, never merged silently).
"""
from __future__ import annotations

import argparse
import copy
import json
import random
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import make_locale_fixtures as M  # noqa: E402
from make_scan_variants import build_pdf  # noqa: E402


def _page(lines):
    return {"w_pt": 612, "h_pt": 792, "ops": M._ops(lines)}


def _lines(d):
    return M.render_lines(d)


def _estimate(claim):
    return ["REPAIR ESTIMATE", f"Claim Number: {claim}", "Estimate No: EST-55120",
            "Insured: Avery Fictional", "Vehicle: 2019 Example Sedan",
            "Parts: $1,240.00", "Labour: $860.00", "Estimate Total: $2,100.00"]


def _cheque(claim):
    return ["FICTIONAL MUTUAL INSURANCE CO.", "Cheque No: 004417", "Date: 2024-05-02",
            "Pay to the order of: Avery Fictional", "Amount: $2,100.00",
            f"Memo: Claim Number {claim}", "⑆021000021⑆ 7743882201⑈ 004417"]


def _release(claim):
    return ["RELEASE OF ALL CLAIMS", f"Claim Number: {claim}",
            "For the sum of $2,100.00 the undersigned releases all claims",
            "arising from the loss of 2024-03-14.", "Signed: Avery Fictional",
            "Date: 2024-05-02"]


def documents(seed=11):
    rng = random.Random(seed)
    inv = [M.invoice("us", rng, "sales tax", 8) for _ in range(3)]
    for k, d in enumerate(inv):
        d["fields"]["Invoice Number"] = f"INV-{4100 + k}"
    st_a = M.bank_statement("us", rng)
    st_b = copy.deepcopy(M.bank_statement("us", rng))
    st_b["fields"]["Account Number"] = "000987654321"
    st_m = copy.deepcopy(st_a)
    st_m["fields"]["Opening Balance"] = st_a["fields"]["Closing Balance"]
    blank = ["   "]
    unref = [["CASH SALE", "Item: Coffee beans", "Amount: $12.00", "Thank you"],
             ["CASH SALE", "Item: Tea", "Amount: $8.00", "Thank you"]]
    out = {
        "invoices_3": ([_lines(d) for d in inv], [0, 1, 2], False),
        "statements_2_accounts": ([_lines(st_a), _lines(st_b)], [0, 1], False),
        "statements_2_months": ([_lines(st_a), _lines(st_m)], [0], True),
        "invoices_blank_sep": ([_lines(inv[0]), blank, _lines(inv[1])], [0, 2], False),
        "claim_packet": ([_estimate("CLM-2024-0091"), _cheque("CLM-2024-0091"),
                          _release("CLM-2024-0091")], [0], True),
        "invoices_unnumbered": (unref, [0], True),
    }
    return {name: {"pages": pages, "starts": starts, "flagged": flagged}
            for name, (pages, starts, flagged) in out.items()}


def pdf(doc) -> bytes:
    return build_pdf([_page(lines) for lines in doc["pages"]])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    out = Path(ap.parse_args().out)
    out.mkdir(parents=True, exist_ok=True)
    truth = {}
    for name, d in documents().items():
        (out / f"{name}.pdf").write_bytes(pdf(d))
        truth[name] = {"starts": d["starts"], "flagged": d["flagged"]}
    (out / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    print(f"{len(truth)} files -> {out}")


if __name__ == "__main__":
    main()
