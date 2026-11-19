"""Thin readers for the real Run A stored-result shape."""
from __future__ import annotations

import importlib
from collections.abc import Callable
from typing import Any

from tests.contract import names


def resolve_callable(path: str) -> Callable[..., Any]:
    module_name, _, attr = path.rpartition(".")
    assert module_name and attr, f"invalid dotted callable name: {path}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"Run A callable is not implemented: {path}") from exc
    target = getattr(module, attr, None)
    assert callable(target), f"Run A callable is not implemented: {path}"
    return target


def state_of(result: dict) -> str:
    state = result.get(names.DOCUMENT_STATE_FIELD)
    assert state in names.DOCUMENT_STATES, (
        f"missing/unknown {names.DOCUMENT_STATE_FIELD}: {state!r}"
    )
    return state


def reasons_of(result: dict) -> list[dict]:
    reasons = result.get(names.ATTENTION_FIELD) or []
    assert isinstance(reasons, list)
    for reason in reasons:
        assert isinstance(reason, dict)
        assert reason.get(names.ATTENTION_ID_FIELD), "every attention reason needs an id"
        assert reason.get(names.ATTENTION_TEXT_FIELD), "every attention reason needs text"
    return reasons


def diagnostics_of(result: dict) -> dict:
    diagnostics = result.get(names.DIAGNOSTICS_FIELD)
    assert isinstance(diagnostics, dict), f"missing {names.DIAGNOSTICS_FIELD}"
    return diagnostics


def coverage_of(result: dict) -> dict:
    coverage = diagnostics_of(result).get(names.COVERAGE_FIELD)
    assert isinstance(coverage, dict), (
        f"missing {names.DIAGNOSTICS_FIELD}.{names.COVERAGE_FIELD}"
    )
    return coverage


def page_ledger_of(result: dict) -> dict[str, str]:
    pages = diagnostics_of(result).get(names.PAGE_LEDGER_FIELD)
    assert isinstance(pages, dict), (
        f"missing {names.DIAGNOSTICS_FIELD}.{names.PAGE_LEDGER_FIELD}"
    )
    return pages


def assert_non_ready_with_reason(result: dict) -> None:
    assert state_of(result) in names.NON_READY_STATES
    assert reasons_of(result), "a non-ready result needs an attention reason"
