"""The replay preflight fails closed.

Every cache key includes the page images, so replay on a machine that renders
them differently misses every lookup and reports 0.0% as though the engine had
failed. The preflight must therefore never pass on missing evidence:
  - a missing, empty, unparseable or incomplete fingerprint file raises
  - a mismatching render raises; no render at all (no Poppler) raises
  - a cache installed in another mode and switched INTO replay runs it too
  - it runs once per process per cache directory, not once per call
The render itself is stubbed: these tests are about the decision, not Poppler.
"""
from __future__ import annotations

import json

import pytest

from tests.harness import llm_cache as lc
from tests.harness.llm_cache import LLMCache, ReplayEnvironmentError

SIG = "51c162ac8cd244a9"


@pytest.fixture
def renders(monkeypatch):
    calls = []

    def fake():
        calls.append(1)
        return SIG
    monkeypatch.setattr(lc, "render_fingerprint", fake)
    return calls


def _cache_dir(tmp_path, content):
    d = tmp_path / "cache"
    d.mkdir()
    if content is not None:
        (d / lc.FINGERPRINT_FILE).write_text(content, encoding="utf-8")
    return d


GOOD = json.dumps({"pdf": lc.FINGERPRINT_PDF, "page": 1, "page_image_sig": SIG,
                   "recorded_with": "test"})


def test_a_matching_fingerprint_passes(tmp_path, renders):
    lc.check_replay_environment(_cache_dir(tmp_path, GOOD))


@pytest.mark.parametrize("content", [
    None,                                         # missing
    "",                                           # empty
    "{not json",                                  # unparseable
    "[]",                                         # not an object
    json.dumps({"pdf": lc.FINGERPRINT_PDF}),      # no signature
    json.dumps({"page_image_sig": ""}),           # empty signature
], ids=["missing", "empty", "unparseable", "not-object", "no-sig", "empty-sig"])
def test_bad_fingerprint_evidence_fails_closed(tmp_path, renders, content):
    with pytest.raises(ReplayEnvironmentError):
        lc.check_replay_environment(_cache_dir(tmp_path, content))


def test_a_different_render_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "render_fingerprint", lambda: "0000000000000000")
    with pytest.raises(ReplayEnvironmentError):
        lc.check_replay_environment(_cache_dir(tmp_path, GOOD))


def test_no_render_at_all_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(lc, "render_fingerprint", lambda: None)
    with pytest.raises(ReplayEnvironmentError):
        lc.check_replay_environment(_cache_dir(tmp_path, GOOD))


def test_install_in_replay_runs_it(tmp_path, renders):
    cache = LLMCache(mode="replay", cache_dir=_cache_dir(tmp_path, None))
    with pytest.raises(ReplayEnvironmentError):
        cache.install()
    cache.uninstall()


def test_switching_an_installed_cache_into_replay_runs_it(tmp_path, renders):
    cache = LLMCache(mode="record", cache_dir=_cache_dir(tmp_path, None))
    cache.install()
    try:
        with pytest.raises(ReplayEnvironmentError):
            cache.mode = "replay"
    finally:
        cache.uninstall()


def test_a_replay_lookup_cannot_bypass_it(tmp_path, renders):
    """Constructed in record mode, never installed through replay, mode
    switched while not installed: the first replay dispatch still checks."""
    cache = LLMCache(mode="record", cache_dir=_cache_dir(tmp_path, None))
    cache.mode = "replay"
    with pytest.raises(ReplayEnvironmentError):
        cache._dispatch("extract", lambda *a, **k: None, None, {"prompt": "x"})


def test_it_runs_once_per_process_per_directory(tmp_path, renders):
    d = _cache_dir(tmp_path, GOOD)
    a = LLMCache(mode="replay", cache_dir=d)
    a.install()
    a.uninstall()
    b = LLMCache(mode="record", cache_dir=d)
    b.install()
    b.mode = "replay"
    b.uninstall()
    assert len(renders) == 1
