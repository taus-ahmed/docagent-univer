"""
Pytest configuration for the accuracy harness.

The bootstrap runs at collection time (before any test module imports
app/engine code) so every test sees production-parity extraction config.
"""
import pytest

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
