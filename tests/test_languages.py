"""Non-Latin and non-English text is flagged, never translated (Part 1.4)."""
from __future__ import annotations

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from scripts import non_latin_scripts, page_language  # noqa: E402
from validators import CheckContext  # noqa: E402

EN = ("Invoice number 42 for the services of March. The total amount is due "
      "within thirty days from the date of this invoice, payable to the account.")
DE = ("Rechnung Nummer 42 für die Leistungen im März. Der Betrag ist mit dem "
      "Datum der Rechnung fällig und nicht von der Bank zu zahlen, bei Fragen.")
FR = ("Facture numéro 42 pour les services du mois. Le montant total est dû "
      "dans les trente jours avec une date sur la facture, par virement au compte.")
HI = "बीजक संख्या ४२ सेवाओं के लिए कुल राशि भुगतान तिथि से तीस दिन के भीतर देय है"
AR = "فاتورة رقم ٤٢ للخدمات المقدمة المبلغ الإجمالي مستحق خلال ثلاثين يوما من التاريخ"
JA = "請求書番号四十二 サービス料金 合計金額はお支払い期日までにお振込みください"


@pytest.mark.parametrize("text,lang", [(EN, "en"), (DE, "de"), (FR, "fr"),
                                       (HI, "script:devanagari"), (AR, "script:arabic"),
                                       (JA, "script:han"), ("Total 12.00", None)])
def test_page_language(text, lang):
    got = page_language(text)
    if lang == "script:han":
        assert got in ("script:han", "script:kana")
    else:
        assert got == lang


def test_scripts_in_a_value():
    assert non_latin_scripts("राशि 500") == ["devanagari"]
    assert non_latin_scripts("ACME Ltd") == []
    assert non_latin_scripts("Иванов") == ["cyrillic"]


def _check(pages, values, value_pages=None, rows=None):
    from language_validators import language_check
    return language_check(CheckContext(fields=[], values=values, pages=pages,
                                       value_pages=value_pages or {}, rows=rows or {}))


def test_values_from_a_foreign_page_are_flagged():
    res = _check([EN, DE], {"B1": "42", "B2": "1.234,56"}, {"B1": 1, "B2": 2})
    bad = [r for r in res if r.status == "unreadable"]
    assert bad and bad[0].slots == ["B2"] and bad[0].reason == "non_english_text"
    langs = next(r for r in res if r.validation.get("page_languages"))
    assert langs.validation["page_languages"] == {1: "en", 2: "de"}


def test_a_non_latin_value_is_flagged_on_an_english_page():
    res = _check([EN], {"B1": "राशि"}, {"B1": 1})
    assert [r.slots for r in res if r.status == "unreadable"] == [["B1"]]


def test_rows_on_a_foreign_page_are_flagged():
    res = _check([EN, HI], {}, rows={"items": [{"a": "x", "_page": 1}, {"a": "y", "_page": 2}]})
    assert [r.slots for r in res if r.status == "unreadable"] == [["items_rows[1]"]]


def test_an_english_record_is_untouched():
    assert _check([EN], {"B1": "42"}, {"B1": 1}) == []


def test_no_english_page_of_the_corpus_is_read_as_foreign():
    """Measured: 114 pages, 0 foreign (two shredded and three ordinary
    English pages were misread before the >=3-letter and English-too rules)."""
    import glob
    import pdfplumber
    bad = []
    for f in sorted(glob.glob(str(bs.TESTS_DIR / "test_pdfs" / "**" / "*.pdf"), recursive=True)):
        with pdfplumber.open(f) as pdf:
            for i, p in enumerate(pdf.pages, 1):
                lang = page_language(p.extract_text() or "")
                if lang not in ("en", None):
                    bad.append((f, i, lang))
    assert not bad, bad
