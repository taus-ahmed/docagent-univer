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


register(ANY, aba_checksum)
register("cheque", amount_cross_check)
register("cheque", micr_band_unreadable)
