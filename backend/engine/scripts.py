# -*- coding: utf-8 -*-
"""Which writing system, and roughly which language, a text is in (Part 1.4).

The engine's prompts, labels, prose checks and number words are English. A
value read from text in another script (Devanagari, Arabic, CJK, Cyrillic, …)
or another Latin-script language is not one the engine can check, so it is
flagged — never translated, never guessed. This module only DETECTS.

`script_counts(text)` counts letters by Unicode block; `page_language(text)`
returns "en", another language code ("de", "fr", "es", "it", "nl", "pt"),
"script:<name>" for a page mostly in another script, or None when there is
too little text to say. Latin-script language is told by function words: a
short heuristic, deliberately conservative — it answers only with at least
eight function-word hits and a clear majority.
"""
from __future__ import annotations

import re
import unicodedata

#: Unicode ranges -> script name (letters only)
_RANGES = [
    (0x0041, 0x024F, "latin"), (0x1E00, 0x1EFF, "latin"),
    (0x0370, 0x03FF, "greek"), (0x0400, 0x052F, "cyrillic"),
    (0x0590, 0x05FF, "hebrew"), (0x0600, 0x06FF, "arabic"), (0x0750, 0x077F, "arabic"),
    (0xFB50, 0xFDFF, "arabic"), (0xFE70, 0xFEFF, "arabic"),
    (0x0900, 0x097F, "devanagari"), (0x0980, 0x09FF, "bengali"),
    (0x0A00, 0x0A7F, "gurmukhi"), (0x0A80, 0x0AFF, "gujarati"),
    (0x0B80, 0x0BFF, "tamil"), (0x0C00, 0x0C7F, "telugu"), (0x0C80, 0x0CFF, "kannada"),
    (0x0D00, 0x0D7F, "malayalam"), (0x0E00, 0x0E7F, "thai"),
    (0x3040, 0x30FF, "kana"), (0x3400, 0x9FFF, "han"), (0xF900, 0xFAFF, "han"),
    (0xAC00, 0xD7AF, "hangul"), (0x1100, 0x11FF, "hangul"),
]


def _script(ch):
    o = ord(ch)
    for lo, hi, name in _RANGES:
        if lo <= o <= hi:
            return name
    return "other"


def script_counts(text) -> dict:
    out: dict = {}
    for ch in str(text or ""):
        if ch.isalpha() or unicodedata.category(ch).startswith("M"):
            s = _script(ch)
            out[s] = out.get(s, 0) + 1
    return out


def non_latin_scripts(text) -> list:
    """Every non-Latin script the text has letters in."""
    return sorted(s for s in script_counts(text) if s not in ("latin", "other"))


_FUNCTION_WORDS = {
    "en": "the and of to in for is on with from by this that are be at as your total date amount".split(),
    "de": "der die das und ist mit von für den des dem nicht ein eine zu bei auf betrag datum".split(),
    "fr": "le la les et des du pour avec une est dans par sur au aux montant total date facture".split(),
    "es": "el la los las y de del para con una por en es al importe fecha factura total".split(),
    "it": "il lo la gli le e di del per con una è in da al importo data fattura totale".split(),
    "nl": "de het een en van voor met is op aan te bedrag datum factuur totaal".split(),
    "pt": "o a os as e de do da para com uma em por ao valor data fatura total".split(),
}
#: words several languages share are not evidence for any one of them, and a
#: foreign word that is ALSO ordinary English ("a", "as", "do", "die", "den",
#: "data") is no evidence against English — the corpus scan read three English
#: pages as Portuguese before this (tests/test_languages.py)
_ENGLISH_TOO = set("a as do da o e em die den das dem is in on per con al op "
                   "te van aan data date total valor for an be to ein".split())
_SHARED = {w for lang, ws in _FUNCTION_WORDS.items() for w in ws
           if sum(w in v for v in _FUNCTION_WORDS.values()) > 1} | _ENGLISH_TOO
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def page_language(text):
    counts = script_counts(text)
    letters = sum(counts.values())
    if letters < 20:
        return None
    top = max(counts, key=counts.get)
    if top not in ("latin", "other") and counts[top] / letters >= 0.3:
        return f"script:{top}"
    words = [w.lower() for w in _WORD.findall(str(text or ""))]
    # A foreign word counts only at three letters or more: a shredded text
    # layer (round2/HTR-043235 p3) is full of "y", "el", "es" fragments.
    hits = {lang: sum(1 for w in words if w in ws and w not in _SHARED
                      and (lang == "en" or len(w) >= 3))
            for lang, ws in _FUNCTION_WORDS.items()}
    total = sum(hits.values())
    if total < 8:
        return None
    best = max(hits, key=hits.get)
    if best != "en" and hits[best] > 2 * hits["en"]:
        return best
    return "en" if hits["en"] >= hits[best] else None


__all__ = ["non_latin_scripts", "page_language", "script_counts"]
