"""Literals taken from the local test documents (Run S, generality rule).

    backend\\.venv\\Scripts\\python.exe tools\\make_forbidden_literals.py

Writes tests/fixtures/forbidden_literals.json, which
tests/test_engine_generality.py checks engine code against, so the check
also runs on CI where local_docs is absent. Three kinds:

  * document names: the parts of every test file's name that are not an
    ordinary word of the trade (`carson`, `fidelity`, `mobile`);
  * proper names: words printed in CAPITALS or Title Case on the documents'
    first page that are not common English or accounting words (a vendor,
    a bank, a person);
  * identifiers: digit runs of 6+ digits printed in the documents (an
    account, a vendor number, a cheque number).

A short allow-list (`_GENERIC`) keeps the trade's own words out of it:
"invoice", "statement", "total" are vocabulary, not document literals.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = [ROOT / "local_docs" / "DocAgent_testdocs"]
OUT = ROOT / "tests" / "fixtures" / "forbidden_literals.json"

_GENERIC = set("""
bank statement invoice invoices receipt receipts payslip paystub stub check checks cheque
cheques form forms report reports list sample samples page pages scan scans scanned photo
photo photos digital long docs doc document documents mod made test copy merchant
brokerage account accounts financial financials expense purchase order orders vendor
vendors income balance sheet monthly annual quarterly summary summaries mileage
detail details schedule tax taxes return returns irs wage wages payroll credit card
cards statement statements combined multi page pdf png jpg jpeg tif tiff small large
blank fill filled fillable full real synthetic simple basic standard template utility
bill bills electric gas water services service corp corporation company inc llc ltd
rotated noisy blurry faded skewed low high res resolution good bad clean dirty dark
light color colour grey gray mono black white table tables with without and the for
one two three four five six seven eight nine ten first second third last new old
""".split())


def _common_words():
    words = set(_GENERIC)
    try:
        sys.path.insert(0, str(ROOT / "backend" / "engine"))
        import text_layer  # noqa: F401  (ensures the engine path works)
    except Exception:
        pass
    return words


_STREET_TYPES = {"street", "avenue", "road", "lane", "drive", "boulevard", "court",
                 "place", "plaza", "parkway", "highway", "circle", "terrace", "suite", "blvd"}
#: "1069 Echo Lane", "424 E. Broad St.": a house number, words, a street type
_STREET = re.compile(r"\b\d{1,6}\s+(?:[A-Za-z.'-]+\s+){1,4}?"
                     r"(?:St|Street|Ave|Avenue|Rd|Road|Ln|Lane|Dr|Drive|Blvd|Boulevard|"
                     r"Way|Ct|Court|Pl|Place|Plaza|Pkwy|Parkway|Hwy|Highway|Cir|Circle|"
                     r"Ter|Terrace)\b\.?")
#: "Grand Rapids, MI 49503": a city, a two-letter state, a ZIP
_CITY = re.compile(r"([A-Z][A-Za-z.' -]{2,30}),\s*[A-Z]{2},?\s+\d{5}(?:-\d{4})?\b")


def name_parts(stem: str):
    return [p for p in re.split(r"[^a-z]+", stem.casefold())
            if len(p) >= 4 and p not in _GENERIC]


def main() -> int:
    import pdfplumber
    common = _common_words()
    names, idents = set(), set()
    files = [p for d in SRC if d.exists() for p in d.rglob("*") if p.is_file()]
    doc_freq, caps, addr = {}, {}, set()
    for p in files:
        names.update(name_parts(p.stem))
        if p.suffix.casefold() != ".pdf":
            continue
        try:
            with pdfplumber.open(str(p)) as pdf:
                text = "\n".join((pg.extract_text() or "") for pg in pdf.pages)
        except Exception:
            continue
        idents.update(re.findall(r"(?<!\d)\d{6,}(?!\d)", text))
        for w in set(re.findall(r"[a-z]{4,}", text.casefold())):
            doc_freq[w] = doc_freq.get(w, 0) + 1
        for w in re.findall(r"\b[A-Z][A-Z&]{4,}\b", text[:3000]):
            caps[w.casefold()] = caps.get(w.casefold(), 0) + 1
        # Run S review: street and city names, which are Title case and so
        # never caught as capitals - read off address-shaped lines
        for line in text.splitlines():
            street = _STREET.search(line)
            if street:
                addr.update(w.casefold() for w in re.findall(r"[A-Za-z]{4,}", street.group(0)))
            city = _CITY.search(line)
            if city:
                addr.update(w.casefold() for w in re.findall(r"[A-Za-z]{4,}", city.group(1)))
    # a word printed in two or fewer of the test documents is that document's
    # own (a vendor, a person, a bank); a word printed in three or more is the
    # trade's vocabulary. Name parts follow the same rule.
    proper = {w for w in caps if w not in common and doc_freq.get(w, 0) <= 2
              and len(w) >= 5}
    names = {w for w in names if doc_freq.get(w, 0) <= 2}
    addr = {w for w in addr if w not in common and w not in _STREET_TYPES
            and doc_freq.get(w, 0) <= 2}
    data = {"document_names": sorted(names), "proper_names": sorted(proper),
            "address_words": sorted(addr), "identifiers": sorted(idents)}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"{len(names)} name parts, {len(proper)} proper names, {len(addr)} address "
          f"words, {len(idents)} identifiers -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
