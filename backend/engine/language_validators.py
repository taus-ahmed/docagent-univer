"""Text the engine cannot check — another script or another language.

`non_english_text` (UNREADABLE: review required, level unchanged) on every
value that has letters of a non-Latin script, or was read from a page whose
text is in another script or (by function words) another Latin-script
language. Nothing is translated or guessed. The language of each page is in
`validation.page_languages`. engine/scripts.py.
"""
from __future__ import annotations

from scripts import non_latin_scripts, page_language
from validators import ANY, UNREADABLE, CheckResult, register

NON_ENGLISH = "non_english_text"


def language_check(ctx):
    numbers = list(ctx.page_numbers) if ctx.page_numbers else \
        list(range(1, len(ctx.pages or []) + 1))
    langs = {}
    for n, text in zip(numbers, ctx.pages or []):
        lang = page_language(text)
        if lang:
            langs[n] = lang
    foreign = {n for n, lang in langs.items() if lang != "en"}
    hits = []
    for ref, v in (ctx.values or {}).items():
        if non_latin_scripts(v) or (ctx.value_pages or {}).get(ref) in foreign:
            hits.append(ref)
    for name, rows in (ctx.rows or {}).items():
        for i, r in enumerate(rows or []):
            if not isinstance(r, dict):
                continue
            cells = [v for k, v in r.items() if not str(k).startswith("_")]
            if r.get("_page") in foreign or any(non_latin_scripts(v) for v in cells):
                hits.append(f"{name}_rows[{i}]")
    out = []
    if langs and set(langs.values()) != {"en"}:
        out.append(CheckResult("language_check", "pass", [], "",
                               validation={"page_languages": langs}))
    if hits:
        out.append(CheckResult(
            "language_check", UNREADABLE, hits, NON_ENGLISH,
            notes=[f"{len(hits)} value(s) were read from text that is not in "
                   f"English; the engine's checks are English-only and the "
                   f"values were not checked by them"],
            validation={"non_english_value_count": len(hits)}))
    return out


register(ANY, language_check)
