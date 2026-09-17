# -*- coding: utf-8 -*-
"""The second-call verification EXPERIMENT (docs/SECOND-CALL-VERIFICATION.md).

NOT A PIPELINE COMPONENT. Nothing here is imported by the engine, and nothing
here changes an extraction. It exists to answer one question with numbers
before any of it is built: can a second, differently-framed call to the same
model detect a value that is real, printed, grounded, correctly typed and
correctly placed, and still answers a different question than the field asked?

    python -m tests.harness.attribution --arm gold      # 10 live calls
    python -m tests.harness.attribution --arm heldout   # 1 live call

THE QUESTION IT ASKS (Q-A). For each value the model is asked two things about
the DOCUMENT, never about our answer:

    party   whose value is this — the issuer, the recipient, a third party, or
            nobody's
    answers which ONE of these field labels does the document present this
            value as answering (closed list, shuffled, "NONE" allowed)

WE do the comparison. The model is never told which slot a value was written
into, so it cannot agree with us by reading our answer back. That is the whole
design constraint, and it comes from `app/core/confidence.py`, which said
before this problem was found that "asking the model whether its own answer
fits its own label is circular".

⚠ The raw response of every live call is written to
`tests/fixtures/attribution_raw/`, so the numbers can be re-read and argued
with rather than only replayed.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

from tests.harness import bootstrap as bs

RAW_DIR = bs.TESTS_DIR / "fixtures" / "attribution_raw"

# ── what kind of thing a value is, so a swap is like for like ───────────────
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", re.I)
_PHONE = re.compile(r"\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}")
_MONEY = re.compile(r"^[\(\-]?\s*[$£€]?\s*[\d,]+(\.\d+)?\s*\)?$")
_DATE = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
                   r"[a-z]*\.?\s+\d{1,2}|^\d{1,2}/\d{1,2}/\d{2,4}$", re.I)
_IDENT = re.compile(r"^[A-Z*][A-Z0-9*\-]{3,}$")


def kind_of(value: str) -> str:
    v = str(value).strip()
    if _EMAIL.search(v):
        return "email"
    if _PHONE.search(v):
        return "phone"
    if _DATE.search(v):
        return "date"
    if _MONEY.match(v):
        return "money"
    if _IDENT.match(v.replace(" ", "")):
        return "identifier"
    if re.search(r"\d", v) and len(v) < 24:
        return "identifier"
    if len(v.split()) >= 2:
        return "name_or_text"
    return "other"


# ── which party a SLOT LABEL implies, if any ────────────────────────────────
#: The comparison side. Deliberately small and explicit: a label that names no
#: party gets NONE and the party signal ABSTAINS on it, which is most of them.
#: `check_placement` abstains the same way when a band's headings are not
#: printed — a verdict on a guess is worse than no verdict.
_RECIPIENT = ("bill to", "customer", "employee", "payee", "account holder",
              "vendor", "supplier", "ship to", "borrower", "client")
_ISSUER = ("employer", "drawer", "buyer", "bank name", "issuer", "our ",
           "company name", "authorised by", "authorized by", "from")


def party_expected(label: str) -> str:
    lab = str(label).casefold()
    for w in _RECIPIENT:
        if w in lab:
            return "RECIPIENT"
    for w in _ISSUER:
        if w in lab:
            return "ISSUER"
    return "NONE"


PROMPT = """You are reading ONE document. Its full text is below.

--- DOCUMENT ---
{doc}
--- END DOCUMENT ---

Below are values that each appear somewhere in that document. For EACH value,
answer two questions FROM THE DOCUMENT ONLY. Do not guess from the shape of the
value; look at where it is printed and what is printed around it.

1. "party" — whose value is it? Exactly one of:
     ISSUER      the party that produced or sent this document
     RECIPIENT   the party the document is addressed to, or that it reports on
     THIRD_PARTY a different named organisation (a bank, a carrier, a tax body)
     NONE        it belongs to no party (a total, a date, the document's own
                 reference number)

2. "answers" — which ONE of these field labels does the document present this
   value as answering? Use the exact spelling from this list, or "NONE" if the
   document does not present it as any of them:
{labels}

3. "printed_label" — the label or heading the document actually prints next to
   or above the value, verbatim. "" if there is none.

Values:
{values}

Return JSON only:
{{"V1": {{"party": "...", "answers": "...", "printed_label": "..."}}, ...}}"""


def _llm():
    bs.bootstrap()
    bs.chdir_backend()
    from connectors.llm_router import LLMRouter
    return LLMRouter()


def ask(doc_text, labels, values, router=None, temperature=0.0):
    """One verification call. `values` is [(vid, value)]."""
    router = router or _llm()
    shown = sorted(set(labels))
    random.Random(17).shuffle(shown)
    prompt = PROMPT.format(
        doc=doc_text,
        labels="\n".join("     - %s" % l for l in shown),
        values="\n".join("%s: %s" % (vid, v) for vid, v in values))
    resp = router.extract(text=" ", prompt=prompt, temperature=temperature,
                          system_instruction=(
                              "You report what a document says about the values "
                              "you are given. You never invent a party or a "
                              "label that the document does not support."))
    raw = getattr(resp, "raw_text", "") or ""
    parsed = getattr(resp, "parsed_json", None)
    if not isinstance(parsed, dict):
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = {}
    return parsed, raw, prompt


def _record(name, payload):
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    payload["captured_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    (RAW_DIR / f"{name}.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")


# ── the corpus under test ───────────────────────────────────────────────────
def population():
    """[(doc, label, value)] for every filled gold field slot, replayed."""
    from tests.harness import witness
    return [(r["doc"], r["label"], r["value"]) for r in witness.measure()]


def swaps(rows):
    """{(doc,label): wrong_value} — a SAME-KIND value from another slot of the
    same document. Real, printed, grounded, correctly typed: the I8 class by
    construction rather than by hand."""
    by_doc = {}
    for doc, lab, val in rows:
        by_doc.setdefault(doc, []).append((lab, val))
    out = {}
    for doc, items in by_doc.items():
        for lab, val in items:
            k = kind_of(val)
            others = [(l2, v2) for l2, v2 in items
                      if l2 != lab and kind_of(v2) == k and v2.strip() != val.strip()]
            if others:
                out[(doc, lab)] = sorted(others)[0][1]
    return out


# ⚠ WHY BOTH ARMS COME OFF THE SAME CALLS. The verifier is never shown which
# slot a value was written into, so its answer for a value is a function of
# (document, value, label list) and NOTHING ELSE. Injecting a wrong assignment
# cannot change what it says. So one call per document measures both arms: the
# false-positive arm compares its answer to the value's TRUE label, the
# true-positive arm to the INJECTED one. Running 115 near-identical calls to
# vary a field the prompt does not contain would measure sampling noise, not
# the gate.
def run_gold(limit_docs=None):
    rows = population()
    sw = swaps(rows)
    by_doc = {}
    for doc, lab, val in rows:
        by_doc.setdefault(doc, []).append((lab, val))

    router = _llm()
    calls, results = [], []
    for doc in sorted(by_doc)[:limit_docs]:
        items = by_doc[doc]
        labels = [l for l, _ in items]
        text = _doc_text(doc)
        vids = {"V%d" % (i + 1): (l, v) for i, (l, v) in enumerate(items)}
        parsed, raw, prompt = ask(text, labels,
                                  [(k, v) for k, (_l, v) in vids.items()],
                                  router=router)
        calls.append({"doc": doc, "raw": raw, "n_values": len(vids),
                      "prompt_chars": len(prompt)})
        print("[ATTR] %-26s %d values, %d chars of prompt"
              % (doc, len(vids), len(prompt)), flush=True)
        for vid, (lab, val) in vids.items():
            a = parsed.get(vid) or {}
            results.append({
                "doc": doc, "true_label": lab, "value": val,
                "kind": kind_of(val),
                "injected_label": None,
                "model_answers": a.get("answers", ""),
                "model_party": a.get("party", ""),
                "printed_label": a.get("printed_label", ""),
                "expected_party": party_expected(lab),
                "swap_value": sw.get((doc, lab)),
            })
    _record("gold_arms", {"calls": calls, "results": results,
                          "model": "gemini-2.5-flash-lite"})
    return results


def _doc_text(doc_id):
    from tests.harness import runner
    for lab in runner.load_labels([doc_id]):
        t = runner.pdf_text(bs.PDF_DIR / lab["pdf"])
        return t if isinstance(t, str) else "\n".join(t)
    return ""


#: The four instances the MODEL ITSELF produced, not ones we constructed.
#: `care@` is round-2 run 9's own answer; the other three are the probe
#: injections recorded in DECISION-LOG §2's 2026-09-15 correction.
HELD_OUT = [
    ("Customer Email Address", "care@engieresources.com", "run 9's own answer"),
    ("Customer Tax ID", "76-0685946", "probe: the supplier's Fed. I.D."),
    ("Late Fee Amount", "$101.99", "probe: the previous balance"),
    ("Deposit Amount", "-$101.99", "probe: the payment received"),
]
BR4_LABELS = ["Bill Account Number", "Billing Period", "Meter Number",
              "Contract End Date", "Customer Tax ID", "Customer Email Address",
              "Late Fee Amount", "Deposit Amount"]


def run_heldout():
    import pdfplumber
    bs.bootstrap()
    bs.chdir_backend()
    from text_layer import read_page

    pdf_path = bs.PDF_DIR / "round2" / "SampleBill.pdf"
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(read_page(p)[0] for p in pdf.pages)

    router = _llm()
    vids = {"V%d" % (i + 1): h for i, h in enumerate(HELD_OUT)}
    parsed, raw, prompt = ask(text, BR4_LABELS,
                              [(k, v) for k, (_l, v, _n) in vids.items()],
                              router=router)
    out = []
    for vid, (lab, val, note) in vids.items():
        a = parsed.get(vid) or {}
        out.append({"assigned_label": lab, "value": val, "note": note,
                    "model_answers": a.get("answers", ""),
                    "model_party": a.get("party", ""),
                    "printed_label": a.get("printed_label", ""),
                    "expected_party": party_expected(lab)})
    _record("heldout", {"raw": raw, "results": out, "prompt_chars": len(prompt),
                        "model": "gemini-2.5-flash-lite"})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["gold", "heldout", "all"], default="all")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    if a.arm in ("gold", "all"):
        run_gold(a.limit)
    if a.arm in ("heldout", "all"):
        run_heldout()
    print("raw written to", RAW_DIR)


if __name__ == "__main__":
    main()
