"""A grounded value whose OWNER is not the party its slot asks about
(Run S, Stage 3a).

Grounding proves a string is printed; it cannot say whose it is. A round-2
utility bill answered `Customer Email Address` with `care@exampleutility.com`: a
real, printed address, and the bill's ISSUER's own customer-care line. The
customer's email is not on the bill at all.

The rule is about ownership, read from the page, never from a list of names:

  * the slot's label names the COUNTERPARTY of the document (the customer,
    client, buyer, recipient, employee, borrower, member, account holder,
    tenant, patient, student, ship-to or bill-to party) - these are the
    trade's words for "the other side", not any document's literals;
  * the value is a contact (an email address, a web address) the ISSUER
    owns: the same contact is printed on two or more pages (letterhead,
    footer, remittance stub), or its domain's name label spells a name
    printed in the first page's letterhead (its first three lines).

Both true -> the value is demoted to Low and flagged, never blanked: the
reader sees the value and the reason. A customer's own address (`pat@mail.com`
on a bill whose issuer is someone else) passes untouched.
"""
from __future__ import annotations

import re

COUNTERPARTY = re.compile(
    r"\b(customer|client|buyer|purchaser|recipient|employee|borrower|member|"
    r"account\s*holder|tenant|patient|student|ship\s*to|bill\s*to|sold\s*to|"
    r"insured|applicant|payee)\b", re.I)
_EMAIL = re.compile(r"^[\w.+-]+@([\w-]+(?:\.[\w-]+)+)$")
_URL = re.compile(r"^(?:https?://)?(?:www\.)?([\w-]+(?:\.[\w-]+)+)(?:/\S*)?$", re.I)
_PUBLIC = {"gmail", "yahoo", "hotmail", "outlook", "aol", "icloud", "live", "msn",
           "proton", "protonmail", "mail", "comcast", "att", "verizon"}


def _domain_label(value):
    v = str(value or "").strip().strip("<>()")
    m = _EMAIL.match(v) or _URL.match(v)
    if not m:
        return None
    parts = m.group(1).casefold().split(".")
    if len(parts) < 2:
        return None
    # the registrable label: the part before the public suffix
    return parts[-2] if len(parts[-1]) >= 2 else None


def _squash(text):
    return re.sub(r"[^a-z0-9]", "", str(text or "").casefold())


def issuer_contact(value, page_texts) -> bool:
    """True when `value` is a contact the document itself owns (its issuer's)."""
    label = _domain_label(value)
    if not label or label in _PUBLIC or len(label) < 4:
        return False
    pages = [str(t or "") for t in page_texts or []]
    v = str(value).strip().casefold()
    on_pages = sum(1 for t in pages if v in t.casefold())
    if on_pages >= 2:
        return True
    # the domain spells a name printed in the letterhead: the first three
    # lines of the first page (a counterparty's own company name is printed
    # often on an invoice too, but not as the document's letterhead)
    first = pages[0].splitlines()[:3] if pages else []
    for line in first:
        if COUNTERPARTY.search(line):
            continue              # "Bill To: Harbor Foods" names the other side
        low = line.casefold().replace(v, " ")
        words = re.findall(r"[a-z0-9&]+", low)
        for i in range(len(words)):
            acc = ""
            for j in range(i, min(i + 4, len(words))):
                acc += words[j]
                if acc == label:
                    return True
                if len(acc) >= len(label):
                    break
    return False


#: "Customer Service", "Client Services", "Customer Care": the ISSUER's own
#: department named after the people it serves - its contact is the issuer's
#: by definition (corpus job 73, a merchant statement's service website)
_ISSUER_DEPT = re.compile(
    r"\b(?:customer|client|member|patient|student)s?\s+"
    r"(?:service|services|care|support|relations|portal|center|centre|hotline|help)\b",
    re.I)


def misowned(label, value, page_texts):
    """A reason string when `value` is the issuer's own contact answering a
    counterparty's slot, else None."""
    if _ISSUER_DEPT.search(str(label or "")):
        return None
    m = COUNTERPARTY.search(str(label or ""))
    if not m or not issuer_contact(value, page_texts):
        return None
    party = m.group(1).lower()
    return (f"this is the document issuer's own contact ({value}, printed as the "
            f"issuer's), but the slot asks for the {party}'s - the {party}'s may "
            f"not be printed at all")
