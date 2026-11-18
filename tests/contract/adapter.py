"""Thin dynamic adapter from provisional Run A names to stable test helpers."""
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


def evaluate_answer(**kwargs) -> dict:
    result = resolve_callable(names.ANSWER_CONTRACT_EVALUATOR)(**kwargs)
    assert isinstance(result, dict), "answer contract must return a mapping"
    return result


def execute_with_retries(**kwargs) -> dict:
    result = resolve_callable(names.RETRY_EXECUTOR)(**kwargs)
    assert isinstance(result, dict), "retry executor must return a mapping"
    return result


def state_of(result: dict) -> str:
    state = result.get(names.DOCUMENT_STATE_FIELD)
    assert state in names.DOCUMENT_STATES, (
        f"missing/unknown {names.DOCUMENT_STATE_FIELD}: {state!r}"
    )
    return state


def reasons_of(result: dict) -> list[dict]:
    diagnostics = result.get(names.DIAGNOSTICS_FIELD) or {}
    reasons = diagnostics.get(names.REASONS_FIELD) or []
    assert isinstance(reasons, list)
    for reason in reasons:
        assert isinstance(reason, dict)
        assert reason.get(names.REASON_CODE_FIELD), "every reason needs a typed code"
    return reasons


def coverage_of(result: dict) -> dict:
    coverage = result.get(names.COVERAGE_FIELD)
    assert isinstance(coverage, dict), f"missing {names.COVERAGE_FIELD}"
    return coverage


def assert_non_ready_with_reason(result: dict) -> None:
    assert state_of(result) in names.NON_READY_STATES
    assert reasons_of(result), "a non-ready result needs a typed reason"
