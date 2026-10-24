"""Cooperative cancellation: a checkpoint the engine passes between pages.

The job thread installs a check (`watching(fn)`) for the duration of one
document; `checkpoint()` calls it and raises `Cancelled` when it answers True.
With no check installed — every caller but the job thread, the harness and the
tests included — `checkpoint()` does nothing, so extraction is unchanged.

`Cancelled` is a BaseException on purpose: the engine has many
`except Exception` blocks that turn a failure into a flagged result, and a
cancel turned into a result would look like a finished document.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager

_local = threading.local()


class Cancelled(BaseException):
    """The job was cancelled; stop this document now."""


@contextmanager
def watching(check):
    """Install `check` (a no-argument callable) for this thread."""
    prev = getattr(_local, "check", None)
    _local.check = check
    try:
        yield
    finally:
        _local.check = prev


def checkpoint() -> None:
    """Raise Cancelled if this thread's job was cancelled; else nothing."""
    check = getattr(_local, "check", None)
    if check is not None and check():
        raise Cancelled()
