"""Identifier validators — one interface, one registry, one file per kind.

    validate(id_type, text) -> Verdict(ok, reason, normalised, note)

`ok` is True (valid), False (invalid: `reason` is the reason code, e.g.
`iban_invalid`) or None (nothing to check: empty). A template declares a
slot's kind as `id_type` on its value cell ("iban", "gstin", ...); the
ANY-family `identifier_check` (identifier_validators.py) runs the plug-in and
applies the result: invalid = exactly low with the reason. Adding a country's
identifier is one file in this package registering itself, plus tests.
Country-level tax ARITHMETIC (GST, VAT lines) is not here: it is declarative
template rules (Part 3.1).
"""
from __future__ import annotations

import importlib
import pkgutil
import re
from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class Verdict:
    ok: Optional[bool]
    reason: str = ""
    normalised: str = ""
    note: str = ""


#: id_type -> (check(normalised) -> (ok, note), reason code)
REGISTRY: dict = {}


def register(id_type: str, reason: str):
    """Decorator: `@register("iban", "iban_invalid")` on `def check(norm)`,
    which receives the normalised text and returns (ok, note)."""
    def wrap(fn: Callable):
        REGISTRY[id_type] = (fn, reason)
        return fn
    return wrap


def normalise(text) -> str:
    """Upper case, spaces / hyphens / dots / slashes removed."""
    return re.sub(r"[\s\-./]", "", str(text or "")).upper()


def validate(id_type, text) -> Verdict:
    _load()
    kind = str(id_type or "").strip().lower()
    if kind not in REGISTRY:
        raise KeyError(f"no identifier plug-in for id_type {id_type!r}")
    fn, reason = REGISTRY[kind]
    norm = normalise(text)
    if not norm:
        return Verdict(None)
    ok, note = fn(norm)
    return Verdict(bool(ok), "" if ok else reason, norm, note or "")


def known_types() -> list:
    _load()
    return sorted(REGISTRY)


def reason_codes() -> set:
    _load()
    return {reason for _fn, reason in REGISTRY.values()}


_loaded = False


def _load():
    global _loaded
    if not _loaded:
        _loaded = True
        for m in pkgutil.iter_modules(__path__):
            importlib.import_module(f"{__name__}.{m.name}")
