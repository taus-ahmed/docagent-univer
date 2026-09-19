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
_AMOUNT_RE = re.compile(rf"{_cls(_AMOUNT)}\s*(\d{{4,12}})\s*{_cls(_AMOUNT)}")

#: A run of digits as an on-us field prints it: digit groups joined by a
#: space or a dash symbol (`1234⑉6678`, `1234d6678`). Never starts or ends on
#: a separator, so a trailing dash stays a terminator rather than being eaten.
_RUN = rf"\d+(?:(?:[ ]|{_cls(_DASH)})\d+)*"
_O = _cls(_ONUS)

#: THE AUXILIARY ON-US FIELD — left of the transit field, bracketed by on-us
#: symbols at both ends. Business cheques carry the serial here.
_AUX_RE = re.compile(rf"{_O}\s*({_RUN})\s*{_O}")
#: An on-us group: optionally opened by an on-us symbol, always CLOSED by one.
#: "The account number is followed by an On-Us symbol to indicate that it is
#: an account number" — that closing symbol is the structural marker.
_GROUP_RE = re.compile(rf"\s*{_O}?\s*({_RUN})\s*{_O}")
#: A serial trailing the account: digits closed by a dash symbol, an amount
#: symbol, or the end of the line.
_TRAIL_RE = re.compile(
    rf"\s*(\d{{3,12}})\s*(?={_cls(_DASH)}|{_cls(_AMOUNT)}|$)")

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

    THE ORDER OF THE ON-US FIELDS IS NOT FIXED, so it is read from STRUCTURE,
    anchored on the transit field, never from position in the string:

        C001002C  A423511613A  559407816184C     business: auxiliary on-us
        (serial)   (transit)   (account)         field LEFT of transit
        A021000021A C7743882201C 001847D         personal: account closed by
                    (account)    (serial)        on-us, serial trailing it

    The on-us field is bank-defined ("the format for this field may vary").
    The first version took the first `on-us … on-us` pair ANYWHERE in the line,
    which on a business cheque is the auxiliary serial — so every business
    cheque reported its cheque number as its account number.

    ⚠ ONE SHAPE IS GENUINELY AMBIGUOUS and is left unanswered: no auxiliary
    field, and TWO on-us-closed groups after the transit field
    (`T…T 0691o 123d6678o` — a documented serial-then-account layout, and
    structurally identical to an account followed by something else). Nothing
    in the band says which is the account, and the routing checksum cannot
    help: it validates the transit field, not which on-us group is which.
    Slot extraction only fills slots the model left EMPTY, so withholding
    costs nothing that a guess would not cost more.
    """
    s = str(line or "")
    if not s:
        return {}
    m = _TRANSIT_RE.search(s)
    if not m:
        return {}
    out = {}
    if aba_is_valid(m.group(1)):
        out["routing_number"] = m.group(1)

    aux = _AUX_RE.search(s[:m.start()])
    right = s[m.end():]
    first = _GROUP_RE.match(right)
    if first is None:
        if aux:
            out["serial_number"] = _digits(aux.group(1))
        return out
    second = _GROUP_RE.match(right, first.end())

    if aux:
        account, serial = first.group(1), aux.group(1)
    elif second:
        return out                      # ambiguous: see the docstring
    else:
        account = first.group(1)
        trail = _TRAIL_RE.match(right, first.end())
        serial = trail.group(1) if trail else ""

    acct = _digits(account)
    if len(acct) >= 4:
        out["account_number"] = acct
    if serial:
        out["serial_number"] = _digits(serial)
    return out


def _digits(run: str) -> str:
    return re.sub(r"\D", "", str(run or ""))


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
