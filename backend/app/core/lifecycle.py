"""Graceful shutdown (Part 2.3).

On SIGTERM uvicorn runs the app's shutdown (main.py lifespan), which calls
`begin_drain()`:

  * new jobs are refused (the upload routes answer 503, "restarting");
  * a running job finishes the FILE it is on — saved whole, one transaction —
    and stops at the next file boundary, listing every file it did not reach
    as interrupted and saying how many were saved ("Interrupted by restart",
    the same wording the boot recovery uses);
  * shutdown waits for that, at most GRACEFUL_SHUTDOWN_SECONDS (minus a
    margin); a job still running then is failed at the next boot by
    `_release_stranded_jobs`, as before.
"""
from __future__ import annotations

import threading
import time

_DRAINING = threading.Event()
_lock = threading.Condition()
_active: set = set()


def draining() -> bool:
    return _DRAINING.is_set()


def begin_drain() -> None:
    _DRAINING.set()


def reset() -> None:
    """Tests only."""
    _DRAINING.clear()


def job_started(job_id) -> None:
    with _lock:
        _active.add(job_id)


def job_finished(job_id) -> None:
    with _lock:
        _active.discard(job_id)
        _lock.notify_all()


def active_jobs() -> set:
    with _lock:
        return set(_active)


def wait_for_jobs(timeout: float) -> set:
    """Wait until no job is running, at most `timeout` s; returns those left."""
    end = time.monotonic() + max(0.0, timeout)
    with _lock:
        while _active:
            left = end - time.monotonic()
            if left <= 0:
                break
            _lock.wait(left)
        return set(_active)


RESTART_REFUSAL = ("The server is restarting and is not taking new jobs. "
                   "Try again in a minute.")
