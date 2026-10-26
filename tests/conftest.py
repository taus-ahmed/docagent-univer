"""
Pytest configuration for the accuracy harness.

The bootstrap runs at collection time (before any test module imports
app/engine code) so every test sees production-parity extraction config.
"""
import os

import pytest

# bcrypt at its minimum cost in tests: the scheme is the same, only slower
# to compute in production (app/core/auth.py, BCRYPT_ROUNDS).
os.environ.setdefault("BCRYPT_ROUNDS", "4")

from tests.harness import bootstrap as _bs

_bs.bootstrap()


@pytest.fixture(scope="session")
def repo_dir():
    return _bs.REPO_DIR


@pytest.fixture(scope="session")
def pdf_dir():
    return _bs.PDF_DIR


@pytest.fixture(scope="session")
def labels_dir():
    return _bs.LABELS_DIR


@pytest.fixture(scope="session")
def templates_dir():
    return _bs.TEMPLATES_DIR


@pytest.fixture(scope="session")
def replay_cache():
    """LLM record/replay cache in strict replay mode: any cache miss raises
    instead of making a network call. Tests that need live calls use the
    ``live`` marker and install the cache in record mode themselves."""
    from tests.harness.llm_cache import LLMCache

    cache = LLMCache(mode="replay")
    cache.install()
    yield cache
    cache.uninstall()


# ── replay portability (docs/proposals/replay-portability.md) ────────────────
#
# Every recorded model answer is keyed by the page images the request carried,
# and those depend on the exact pdftoppm and Pillow that rendered them. On a
# machine that renders differently the replay preflight raises
# ReplayEnvironmentError rather than let every lookup miss.
#
# DOCAGENT_REPLAY_ENV decides what that means for a test run:
#   require (default) — the error stands: the test errors. Locally, a wrong
#                       Poppler is a setup mistake to fix, not to skip.
#   skip              — the test is SKIPPED, with the reason naming the
#                       mismatch, and the run ends with a count of them. CI
#                       sets this: an environment difference is never a
#                       failure there, and never a silent pass.
# Tests that use the replay cache carry the `replay` marker (applied below),
# so `-m replay` / `-m "not replay"` selects them explicitly.

_REPLAY_MODULES = {"test_batch_end_to_end.py", "test_batch_isolation.py",
                   "test_transposed_case.py"}
_REPLAY_SKIPS: list = []


def _replay_policy() -> str:
    return (os.environ.get("DOCAGENT_REPLAY_ENV") or "require").strip().lower()


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "replay: replays recorded model answers; needs the pdftoppm "
                   "and Pillow that recorded tests/llm_cache "
                   "(DOCAGENT_REPLAY_ENV=skip skips them, named, on a mismatch)")


def pytest_collection_modifyitems(config, items):
    for item in items:
        if ("replay_cache" in getattr(item, "fixturenames", ())
                or item.path.name in _REPLAY_MODULES):
            item.add_marker(pytest.mark.replay)


def _as_replay_skip(item, exc):
    """Under `skip`, a MARKED test's mismatch becomes a named skip. An
    UNMARKED test's is left to fail (Run 15): a test that quietly came to
    depend on the replay cache must say so with the marker, not vanish."""
    from tests.harness.llm_cache import ReplayEnvironmentError
    if isinstance(exc, ReplayEnvironmentError) and _replay_policy() == "skip":
        marked = item.get_closest_marker("replay") is not None
        _REPLAY_SKIPS.append((item.nodeid, marked))
        if marked:
            pytest.skip("REPLAY ENVIRONMENT MISMATCH (not a test failure): "
                        + str(exc).split(". ")[0])


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    try:
        return (yield)
    except BaseException as exc:      # ReplayAbort is a BaseException
        _as_replay_skip(item, exc)
        raise


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    try:
        return (yield)
    except BaseException as exc:      # ReplayAbort is a BaseException
        _as_replay_skip(item, exc)
        raise


def pytest_terminal_summary(terminalreporter):
    if not _REPLAY_SKIPS:
        return
    marked = [n for n, m in _REPLAY_SKIPS if m]
    unmarked = [n for n, m in _REPLAY_SKIPS if not m]
    if marked:
        terminalreporter.write_sep(
            "=", f"{len(marked)} replay-dependent test(s) SKIPPED: this "
                 f"machine renders page images differently from the one that "
                 f"recorded tests/llm_cache", yellow=True)
    if unmarked:
        terminalreporter.write_sep(
            "=", f"{len(unmarked)} UNMARKED test(s) raised "
                 f"ReplayEnvironmentError and FAILED (mark them `replay`)",
            red=True)
        for n in unmarked:
            terminalreporter.write_line(f"  {n}")
