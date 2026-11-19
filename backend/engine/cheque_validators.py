"""Cheque-family checks, behind the validator registry (validators.py).

Moved out of slot_extractor/extractor unchanged in effect:
  amount_cross_check   figures vs words (cheque_amounts.compare_amounts)
  micr_band_unreadable a band is printed and not one digit of it is readable
  aba_checksum         registered for ANY family — a routing number is
                       checkable wherever it is printed (a statement's `ABA`
                       slot was checked before this file existed)
"""
from __future__ import annotations

import re

from cheque_amounts import compare_amounts
from micr import aba_is_valid, band_count, field_role, find_micr_line, transit_number
from validators import ANY, FAIL, PASS, UNREADABLE, CheckResult, register

AMOUNT_MISMATCH = "amount_mismatch"
AMOUNT_UNREADABLE = "amount_unreadable"
CHECKSUM_FAILED = "checksum_failed"
MICR_UNREADABLE = "micr_band_unreadable"

_FIGURE_WORDS = {"figures", "figure", "numeric", "numerals", "numeral",
                 "digits", "courtesy"}
_WRITTEN_WORDS = {"words", "written", "legal"}


def amount_role(label):
    """'figures' | 'words' | '' — which statement of a cheque's amount a slot
    asks for. The template's and the vocabulary's names are `Amount in Figures`
    and `Amount in Words`. A bare `Amount` is NEITHER: nothing says which of
    the two it is (a cheque prints its amount twice, vocabulary.py)."""
    words = set(re.sub(r"[^a-z ]+", " ", str(label or "").lower()).split())
    if "amount" not in words:
        return ""
    if words & _WRITTEN_WORDS:
        return "words"
    if words & _FIGURE_WORDS:
        return "figures"
    return ""


def aba_checksum(ctx):
    """Every routing slot, whoever filled it, against the ABA check digit; and
    the MICR band's own transit field, whose withholding (parse_micr refuses a
    failing one) must not leave a silently empty slot."""
    micr_line = find_micr_line(ctx.pages)
    transit = transit_number(micr_line) if micr_line else ""
    band = None if not transit else ("pass" if aba_is_valid(transit) else "fail")
    out = [CheckResult("aba_checksum_band",
                       {None: UNREADABLE, "pass": PASS, "fail": FAIL}[band],
                       validation={"routing_checksum": band})]
    for f in ctx.fields:
        if field_role(f["row_label"]) != "routing":
            continue
        ref = f["ref"]
        if ref in ctx.values:
            ok = aba_is_valid(re.sub(r"\D", "", str(ctx.values[ref])))
            out.append(CheckResult(
                "aba_checksum", PASS if ok else FAIL, [ref],
                "" if ok else CHECKSUM_FAILED,
                evidence={ref: {"aba_checksum": "pass" if ok else "fail"}},
                flags=[] if ok else [(
                    f["row_label"], ctx.values[ref],
                    "fails the ABA routing checksum — these digits cannot be a "
                    "routing number as read")]))
        elif band == "fail":
            out.append(CheckResult(
                "aba_checksum", FAIL, [], CHECKSUM_FAILED,
                flags=[(f["row_label"], transit,
                        "the MICR band's routing number fails the ABA checksum, "
                        "so it was not reported — read it from the cheque")],
                notes=[f'{f["row_label"]}: MICR routing number {transit} fails '
                       f"the ABA checksum — left empty"],
                needs_review=True))
    return out


def amount_cross_check(ctx):
    """Runs only when exactly one slot asks for each statement and BOTH were
    filled. MISMATCH: both exactly low — at least one is wrong and nothing
    says which. UNREADABLE: a notice on both. MATCH: evidence only."""
    by_role, label = {}, {}
    for f in ctx.fields:
        role = amount_role(f["row_label"])
        if role:
            by_role.setdefault(role, []).append(f["ref"])
            label[f["ref"]] = f["row_label"]
    if len(by_role.get("figures", [])) != 1 or len(by_role.get("words", [])) != 1:
        return []
    fig, wrd = by_role["figures"][0], by_role["words"][0]
    if fig not in ctx.values or wrd not in ctx.values:
        return []
    check = compare_amounts(str(ctx.values[fig]), str(ctx.values[wrd]))
    evidence = {ref: {"amount_cross_check": check.status} for ref in (fig, wrd)}
    if check.status == "mismatch":
        return [CheckResult(
            "amount_cross_check", FAIL, [fig, wrd], AMOUNT_MISMATCH, evidence,
            flags=[(label[ref], ctx.values[ref],
                    f"amount in figures ({check.numeric}) and amount in words "
                    f"({check.words}) disagree — at least one of them is wrong")
                   for ref in (fig, wrd)],
            notes=[f"cheque amount cross-check: figures {check.numeric} vs "
                   f"words {check.words} — MISMATCH, both values marked low"])]
    if check.status == "unreadable":
        return [CheckResult(
            "amount_cross_check", UNREADABLE, [fig, wrd], AMOUNT_UNREADABLE,
            evidence, notes=["cheque amount cross-check could not be completed "
                             "— " + ", ".join(check.reasons)])]
    return [CheckResult("amount_cross_check", PASS, [fig, wrd], "", evidence)]


def micr_band_unreadable(ctx):
    """ONE band on the record, and not one digit of it readable. The values
    that depend on the band's identity (routing, account) say so; an identity
    slot left empty is flagged rather than silently blank."""
    counts = [band_count(t) for t in ctx.pages]
    readable = sum(c[0] for c in counts)
    if not (readable == 0 and sum(c[1] for c in counts) == 1):
        return []
    ident = [f for f in ctx.fields if field_role(f["row_label"])]
    return [CheckResult(
        "micr_band_unreadable", UNREADABLE,
        [f["ref"] for f in ident if f["ref"] in ctx.values], MICR_UNREADABLE,
        flags=[(f["row_label"], "",
                "the cheque's MICR band is printed but could not be read, so "
                "this value was not taken from it — read it from the cheque")
               for f in ident if f["ref"] not in ctx.values],
        notes=["the MICR band could not be read — routing and account are not "
               "verified against it"],
        validation={"micr_band_unreadable": True}, needs_review=True)]


ROUTING_CHECKSUM_FAILED = "routing_checksum_failed"
POSSIBLE_SWAP = "possible_swap"
CHEQUE_NUMBER_MISSING = "cheque_number_missing"
CHEQUE_NUMBER_MISMATCH = "cheque_number_mismatch"

_CHQ_WORDS = {"cheque", "check", "chq", "chk", "serial"}
_NO_WORDS = {"no", "number", "num", "nr"}


def is_cheque_number_label(label) -> bool:
    """`Cheque Number`, `Check #`, `Chq No`, `Serial Number`, `Check No.`."""
    raw = str(label or "").lower()
    words = set(re.sub(r"[^a-z0-9 ]+", " ", raw).split())
    if not words & _CHQ_WORDS or field_role(label):
        return False
    return bool(words & _NO_WORDS) or "#" in raw or words == {"serial"}


def _digits(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _routing_ok(d: str) -> bool:
    """Exactly nine digits passing 3(d1+d4+d7) + 7(d2+d5+d8) + (d3+d6+d9) ≡ 0
    (mod 10) — the ABA check digit, applied only to nine digits."""
    return len(d) == 9 and aba_is_valid(d)


def _bottom_groups(pages) -> list:
    """The digit groups of the MICR band, in printed order ([] without one)."""
    line = find_micr_line(pages)
    return re.findall(r"\d+", line) if line else []


_LABELLED_NO = re.compile(r"(?:\bno\b\.?|#|\bnumber\b)\s*:?\s*(?:[a-z]{2,4}-)?(\d{3,8})\b",
                          re.I)
_LINE_END_NO = re.compile(r"(?:^|\s)(\d{3,6})\s*$")


def _top_number(pages) -> str:
    """The cheque number printed near the top right, from the first three
    lines of the first page: a number after a number label (`No: CHQ-001847`,
    `Check # 1004`), else a 3–6 digit token that ENDS its line (`First Union
    Bank 001004`). A number inside a line is not taken — on gold CHQ-001847
    that was the bank's street number (`330 Madison Ave`). '' when none."""
    first = next((p for p in pages or [] if isinstance(p, str) and p), "")
    lines = first.splitlines()[:3]
    for ln in lines:
        m = _LABELLED_NO.search(ln)
        if m:
            return m.group(1)
    for ln in lines:
        m = _LINE_END_NO.search(ln)
        if m:
            return m.group(1)
    return ""


def bottom_line(ctx):
    """Run C, C7 — the cheque's bottom line: cheque number, routing number,
    account number, each in its own slot.

    A moderate-quality scan put these into the wrong slots SILENTLY: every
    value was grounded (the digits are on the page) and nothing compared them
    with what a routing number must be. This makes a wrong assignment
    VISIBLE; it does not make the reading correct, and it never moves a
    value from one slot to another.

      routing   exactly 9 digits passing the ABA checksum, else low with
                `routing_checksum_failed`
      swap      the routing value fails but the ACCOUNT value is 9 digits that
                pass: both low with `possible_swap`, and the flag names the
                suggested correction — the values stay where they were
      cheque #  empty while the bottom line carries a 3–6 digit group: flagged
                (`cheque_number_missing`); filled but different from the
                number printed top right: low (`cheque_number_mismatch`)
    """
    role = {}
    for f in ctx.fields:
        lab = f.get("row_label", "")
        r = field_role(lab) or ("cheque_number" if is_cheque_number_label(lab) else "")
        if r:
            role.setdefault(r, []).append(f)
    out = []
    routing = [f for f in role.get("routing", []) if f["ref"] in ctx.values
               and _digits(ctx.values[f["ref"]])]
    accounts = [f for f in role.get("account", []) if f["ref"] in ctx.values]
    for f in routing:
        ref, d = f["ref"], _digits(ctx.values[f["ref"]])
        if _routing_ok(d):
            continue
        why = ("is not 9 digits" if len(d) != 9 else "fails the ABA checksum")
        out.append(CheckResult(
            "bottom_line", FAIL, [ref], ROUTING_CHECKSUM_FAILED,
            evidence={ref: {"routing_checksum": "fail"}},
            flags=[(f["row_label"], ctx.values[ref],
                    f"routing_checksum_failed: {d} {why} — a routing number is "
                    f"exactly 9 digits that pass the ABA checksum")]))
        for a in accounts:
            ad = _digits(ctx.values[a["ref"]])
            if _routing_ok(ad) and ad != d:
                said = (f"possible_swap: the account value {ad} is a valid "
                        f"routing number and the routing value {d} is not — "
                        f"suggested: {f['row_label']} = {ad}, {a['row_label']} "
                        f"= {d}. Not changed: check the cheque's bottom line.")
                out.append(CheckResult(
                    "bottom_line", FAIL, [ref, a["ref"]], POSSIBLE_SWAP,
                    evidence={ref: {"suggested": ad}, a["ref"]: {"suggested": d}},
                    flags=[(f["row_label"], ctx.values[ref], said),
                           (a["row_label"], ctx.values[a["ref"]], said)],
                    notes=[said]))
    groups = _bottom_groups(ctx.pages)
    short = [g for g in groups if 3 <= len(g) <= 6]
    top = _top_number(ctx.pages)
    for f in role.get("cheque_number", []):
        ref = f["ref"]
        have = _digits(ctx.values.get(ref, ""))
        if not have:
            if short:
                out.append(CheckResult(
                    "bottom_line", UNREADABLE, [], CHEQUE_NUMBER_MISSING,
                    flags=[(f["row_label"], "",
                            f"cheque_number_missing: the bottom line carries "
                            f"{short[0]}, which is shaped like a cheque number, "
                            f"and this slot is empty — read it from the cheque")],
                    needs_review=True))
            continue
        if top and int(have) != int(top):
            out.append(CheckResult(
                "bottom_line", FAIL, [ref], CHEQUE_NUMBER_MISMATCH,
                flags=[(f["row_label"], ctx.values[ref],
                        f"cheque_number_mismatch: {ctx.values[ref]} is not the "
                        f"number printed at the top right ({top})")]))
    return out


register(ANY, aba_checksum)
register("cheque", amount_cross_check)
register("cheque", micr_band_unreadable)
register("cheque", bottom_line)
