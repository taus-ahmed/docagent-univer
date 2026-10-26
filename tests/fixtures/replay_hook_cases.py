"""Cases for tests/test_replay_skip_hook.py — run only through a subprocess.

Not named test_*.py, so the ordinary suite never collects it; the hook test
names the file explicitly.
"""
import pytest


def _mismatch():
    from tests.harness.llm_cache import ReplayEnvironmentError
    raise ReplayEnvironmentError("this machine renders differently. details")


@pytest.mark.replay
def test_marked_replay_mismatch():
    _mismatch()


def test_unmarked_replay_mismatch():
    _mismatch()


def test_ordinary_pass():
    assert True
