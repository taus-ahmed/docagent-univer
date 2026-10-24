"""engine/cancellation.py: a no-op unless the job thread installs a check, and
the OCR pool stops starting pages once a job is cancelled."""
from concurrent.futures import Future

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

import cancellation  # noqa: E402
from core import preprocessor  # noqa: E402


def test_checkpoint_does_nothing_without_a_check():
    cancellation.checkpoint()


def test_checkpoint_raises_once_the_check_says_so():
    flag = {"v": False}
    with cancellation.watching(lambda: flag["v"]):
        cancellation.checkpoint()
        flag["v"] = True
        with pytest.raises(cancellation.Cancelled):
            cancellation.checkpoint()
    cancellation.checkpoint()            # uninstalled on exit


def test_cancelled_is_not_an_exception():
    """The engine's `except Exception` blocks must not turn it into a result."""
    assert not issubclass(cancellation.Cancelled, Exception)


class _Pool:
    def __init__(self, max_workers=None, **_):
        self.futures = []

    def submit(self, fn, *args):
        f = Future()
        self.futures.append(f)
        return f

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_a_cancel_cancels_the_pages_not_started(monkeypatch):
    pools = []

    def factory(max_workers=None):
        pools.append(_Pool())
        return pools[-1]
    monkeypatch.setenv("OCR_WORKERS", "3")
    monkeypatch.setattr(preprocessor, "_POOL_FACTORY", factory)
    with cancellation.watching(lambda: True):
        with pytest.raises(cancellation.Cancelled):
            preprocessor._prefetch_ocr("x.pdf", [1, 2, 3])
    assert pools and all(f.cancelled() for f in pools[0].futures)
