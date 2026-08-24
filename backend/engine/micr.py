"""
DocAgent — MICR line decomposition

The MICR band along the bottom of a cheque is not free text. It is E-13B, and
every field in it is delimited by a sentinel character that means one thing:

    ⑆ transit   the 9-digit ABA routing number of the drawee bank
    ⑈ on-us     the account number (and often the serial, bank's choice)
    ⑇ amount    the amount, encoded by the first bank to handle the item
    ⑉ dash      a separator inside the on-us field

OCR and PDF text extraction rarely preserve those glyphs. They come through as
ASCII stand-ins, and which stand-in depends on the font vendor: the transit
symbol is commonly `A`, `T` or `:`, on-us `C` or `O`, amount `B`, dash `D` or
`-`. So a real MICR line reaches us looking like

    A021000021A C7743882201C 001847D

and the model, asked for a routing number and an account number, returns the
whole line and nothing else. That is not a naming problem and no prompt fixes
it: the line has a fixed format, so it is PARSED.

The routing number is then checked against the ABA checksum, which is what
makes this safe rather than positional guessing — nine digits in the transit
position that fail the checksum are not a routing number, and are not reported
as one.
"""

import re

#: Sentinel stand-ins, by role. A vendor picks one glyph per role; we accept
#: any of them and never assume a particular one.
_TRANSIT = "A T t : ⑆"
_ONUS = "C O o ⑈"
_AMOUNT = "B ⑇"
_DASH = "D d ⑉ -"


def _cls(chars):
    return "[" + re.escape("".join(chars.split())) + "]"


#: A field is <sentinel> digits <sentinel>, the sentinels being the same role.
_TRANSIT_RE = re.compile(rf"{_cls(_TRANSIT)}\s*(\d{{9}})\s*{_cls(_TRANSIT)}")
_ONUS_RE = re.compile(rf"{_cls(_ONUS)}\s*([\d{re.escape('-')}\s]{{4,20}}?)\s*{_cls(_ONUS)}")
_AMOUNT_RE = re.compile(rf"{_cls(_AMOUNT)}\s*(\d{{4,12}})\s*{_cls(_AMOUNT)}")

#: A line that plausibly IS a MICR band: at least a transit field, mostly
#: digits and sentinels. Deliberately strict — a sentence containing a nine
#: digit number is not a MICR line.
_LOOKS_MICR = re.compile(
    rf"{_cls(_TRANSIT)}\s*\d{{9}}\s*{_cls(_TRANSIT)}")


def aba_is_valid(routing: str) -> bool:
    """The ABA routing check digit: 3·(d1+d4+d7) + 7·(d2+d5+d8) + (d3+d6+d9)
    must be a multiple of 10. Nine digits that fail it are not a routing
    number, whatever position they were printed in."""
    d = [int(c) for c in str(routing or "") if c.isdigit()]
    if len(d) != 9:
        return False
    total = (3 * (d[0] + d[3] + d[6])
             + 7 * (d[1] + d[4] + d[7])
             + (d[2] + d[5] + d[8]))
    return total % 10 == 0


def find_micr_line(text) -> str:
    """The document's MICR band, or ''. Takes a string or a list of pages."""
    pages = text if isinstance(text, (list, tuple)) else [text]
    for page in pages:
        for line in str(page or "").split("\n"):
            if _LOOKS_MICR.search(line):
                return line.strip()
    return ""


def parse_micr(line: str) -> dict:
    """{routing_number, account_number, serial_number} — only the parts that
    are actually there, and only when they are certainly what they claim.

    Returns {} for anything that is not a MICR band. A routing number is
    reported only if it passes the ABA checksum; reporting an unchecked one
    would be exactly the kind of confident wrong answer this whole engine is
    built to avoid.
    """
    s = str(line or "")
    if not s:
        return {}
    out = {}

    m = _TRANSIT_RE.search(s)
    if m and aba_is_valid(m.group(1)):
        out["routing_number"] = m.group(1)

    m = _ONUS_RE.search(s)
    if m:
        acct = re.sub(r"[\s-]", "", m.group(1))
        if acct.isdigit() and len(acct) >= 4:
            out["account_number"] = acct

    # The serial usually trails the on-us field, closed by the dash sentinel.
    tail = s[m.end():] if m else s
    m2 = re.search(rf"(\d{{3,12}})\s*{_cls(_DASH)}", tail)
    if m2:
        out["serial_number"] = m2.group(1)

    return out


#: Standard synonyms for the two values that live inside a MICR band. These are
#: names for ONE thing each — a bank's ABA/transit/routing number, and the
#: account it identifies — not a vocabulary of loosely related terms.
_ROUTING_WORDS = ("routing", "aba", "transit")
_ACCOUNT_WORDS = ("account",)
_NUMBERISH = ("number", "no", "num", "#")


def field_role(label: str) -> str:
    """'routing' | 'account' | '' — what a slot with this label wants."""
    lab = re.sub(r"[^a-z0-9 ]+", " ", str(label or "").lower())
    words = set(lab.split())
    if words & set(_ROUTING_WORDS):
        return "routing"
    if words & set(_ACCOUNT_WORDS) and (words & set(_NUMBERISH)):
        return "account"
    return ""
