"""classify_by_hints matches a hint as a WHOLE WORD (Part 3.2).

It matched substrings, so the tax-form hint `tin` fired inside "continued",
"routine", "stinging" and "continental", `pan` inside "company", `irs` inside
"first". A boundary is required only on a side where the hint itself ends in a
letter or digit, so stems that end in punctuation (`inv-`, `p.o.`, `po #`)
still match "INV-2024-0031" and "P.O. 1234".
"""
import pytest

from app.services.prompt_registry import _hint_in, classify_by_hints


@pytest.mark.parametrize("word", ["continued", "routine", "stinging", "continental"])
def test_a_short_hint_does_not_fire_inside_a_word(word):
    assert not _hint_in("tin", f"page 2 {word} on the next page")


def test_a_hint_fires_as_a_word():
    assert _hint_in("tin", "tin: 12-3456789")
    assert _hint_in("pan", "pan aaapl1234c")
    assert not _hint_in("pan", "company name")
    assert not _hint_in("irs", "first quarter")


@pytest.mark.parametrize("hint,text", [("inv-", "inv-2024-0031"), ("p.o.", "p.o. 1234"),
                                       ("po #", "po #4471"), ("w-2", "form w-2 wage")])
def test_punctuated_stems_still_match(hint, text):
    assert _hint_in(hint, text)


def test_continuation_text_alone_is_not_a_tax_form():
    text = "Statement continued. Routine maintenance on the continental account."
    assert classify_by_hints(text) != "tax_form"
