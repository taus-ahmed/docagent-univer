from __future__ import annotations

from collections import deque

import pytest

from tests.contract.adapter import execute_with_retries


RUN_A2 = pytest.mark.xfail(
    strict=True,
    reason="Run A2: bounded typed retries with injectable backoff are not implemented",
)


class PlannedOperation:
    def __init__(self, outcomes):
        self.outcomes = deque(outcomes)
        self.calls = []

    def __call__(self, *, section="full_document"):
        self.calls.append(section)
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class HttpFailure(RuntimeError):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


@pytest.mark.parametrize("status", [429, 503])
@RUN_A2
def test_transient_http_failures_retry_with_bounded_injected_backoff(status):
    operation = PlannedOperation([HttpFailure(status), {"ok": True}])
    delays = []
    result = execute_with_retries(
        operation=operation,
        sleep=delays.append,
        jitter=lambda: 0.25,
        max_attempts=3,
        section="full_document",
    )
    assert result["ok"] is True
    assert len(operation.calls) == 2
    assert delays and all(0 <= delay <= 30 for delay in delays)


@pytest.mark.parametrize(
    "failure",
    [ValueError("invalid request"), OSError("corrupt PDF")],
    ids=["invalid-request", "corrupt-pdf"],
)
@RUN_A2
def test_permanent_input_failures_are_not_retried(failure):
    operation = PlannedOperation([failure, {"ok": True}])
    result = execute_with_retries(
        operation=operation,
        sleep=lambda _delay: None,
        jitter=lambda: 0.0,
        max_attempts=3,
        section="full_document",
    )
    assert result["attempts"] == 1
    assert len(operation.calls) == 1


@RUN_A2
def test_max_tokens_retries_only_the_truncated_section():
    operation = PlannedOperation([
        {"finish_reason": "MAX_TOKENS", "section": "transactions"},
        {"ok": True, "section": "transactions"},
    ])
    result = execute_with_retries(
        operation=operation,
        sleep=lambda _delay: None,
        jitter=lambda: 0.0,
        max_attempts=3,
        section="transactions",
        completed_sections={"header": {"fields": {"F1": "kept"}}},
    )
    assert operation.calls == ["transactions", "transactions"]
    assert result["completed_sections"]["header"]["fields"]["F1"] == "kept"


@RUN_A2
def test_total_attempts_are_bounded():
    operation = PlannedOperation([HttpFailure(503)] * 10)
    result = execute_with_retries(
        operation=operation,
        sleep=lambda _delay: None,
        jitter=lambda: 0.0,
        max_attempts=3,
        section="full_document",
    )
    assert result["attempts"] == 3
    assert len(operation.calls) == 3


@RUN_A2
def test_partial_answer_is_never_zero_filled():
    operation = PlannedOperation([
        {"fields": {"F1": {"value": "kept"}}, "tables": None},
    ])
    result = execute_with_retries(
        operation=operation,
        sleep=lambda _delay: None,
        jitter=lambda: 0.0,
        max_attempts=1,
        section="full_document",
    )
    answer = result.get("answer") or {}
    assert answer.get("fields", {}).get("F1", {}).get("value") == "kept"
    assert answer.get("tables") is not None
    assert 0 not in answer.get("fields", {}).values()
