"""The image-independent alias key (round 12 B1; docs/proposals/replay-portability.md).

Every recorded answer is keyed by its exact request, page-image bytes included,
so a machine whose Poppler or Pillow encodes the same page differently misses
every lookup. For a NATIVE-TEXT document — no page was OCR'd, so the text and
prompt do not depend on the render — `_alias_index.json` maps an alias key
(the request with each image's bytes replaced by its width and height) to the
exact key it was recorded under. Replay tries the exact key first, then the
alias; OCR-derived requests have no alias and keep the exact key and the
render preflight. A miss is never silent.
"""
from __future__ import annotations

import base64
import io
import json

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from tests.harness import llm_cache as lc  # noqa: E402


def _jpeg(w, h, shade):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (shade, shade, shade)).save(buf, "JPEG")
    return base64.b64encode(buf.getvalue()).decode()


REQ = dict(prompt="Fill F1", system_instruction="sys", model=None, text="")


class _Router:
    calls = 0

    def extract(self, **kw):           # replaced by the cache when installed
        _Router.calls += 1
        raise AssertionError("replay reached the provider")

    def classify(self, **kw):
        raise AssertionError("replay reached the provider")


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """A cache recorded on 'the old machine' with image A, and an index."""
    from connectors.base import LLMResponse
    img_old = _jpeg(40, 30, 10)
    key = lc.request_key("extract", image_b64=[img_old], **REQ)
    cache = lc.LLMCache(mode="replay", cache_dir=tmp_path)
    cache._save(key, "extract", REQ["prompt"], None,
                LLMResponse(raw_text="{}", parsed_json={"fields": {"F1": "x"}},
                            model_used="m", tokens_used=1, success=True))
    alias = lc.alias_key("extract", image_b64=[img_old], **REQ)
    lc.write_alias_index(tmp_path, {alias: key})
    (tmp_path / lc.FINGERPRINT_FILE).write_text(
        json.dumps({"page_image_sig": "recorded-elsewhere"}), encoding="utf-8")
    # This machine renders differently from the recording one.
    monkeypatch.setattr(lc, "render_fingerprint", lambda: "this-machine")
    lc._PREFLIGHT_PASSED.clear()
    return tmp_path


def _install(cache_dir, monkeypatch):
    import connectors.llm_router as router_mod
    monkeypatch.setattr(router_mod, "LLMRouter", _Router)
    c = lc.LLMCache(mode="replay", cache_dir=cache_dir)
    c.install()
    return c


def test_alias_key_ignores_image_bytes_but_not_their_shape():
    a = lc.alias_key("extract", image_b64=[_jpeg(40, 30, 10)], **REQ)
    assert a == lc.alias_key("extract", image_b64=[_jpeg(40, 30, 200)], **REQ)
    assert a != lc.alias_key("extract", image_b64=[_jpeg(41, 30, 10)], **REQ)
    assert a != lc.alias_key("extract", image_b64=[_jpeg(40, 30, 10)] * 2, **REQ)
    assert a != lc.alias_key("extract", image_b64=[_jpeg(40, 30, 10)],
                             **{**REQ, "prompt": "Fill F2"})
    assert a != lc.request_key("extract", image_b64=[_jpeg(40, 30, 10)], **REQ)


def test_a_re_rendered_native_text_request_replays_by_alias(cache_dir, monkeypatch):
    c = _install(cache_dir, monkeypatch)
    try:
        resp = _Router().extract(image_b64=[_jpeg(40, 30, 99)], **REQ)
    finally:
        c.uninstall()
    assert resp.parsed_json == {"fields": {"F1": "x"}}
    assert c.stats["alias_hits"] == 1 and c.stats["hits"] == 0


def test_a_request_with_no_alias_still_needs_the_render(cache_dir, monkeypatch):
    """An OCR-derived request has no alias: on a machine that renders
    differently it is the preflight's named error, never a silent miss."""
    c = _install(cache_dir, monkeypatch)
    try:
        with pytest.raises(lc.ReplayEnvironmentError):
            _Router().extract(image_b64=[_jpeg(40, 30, 99)],
                              **{**REQ, "prompt": "OCR text differs"})
    finally:
        c.uninstall()
    assert c.stats["misses"] == 1


def test_without_an_index_a_mismatched_render_fails_at_install(cache_dir, monkeypatch):
    (cache_dir / lc.ALIAS_INDEX_FILE).unlink()
    import connectors.llm_router as router_mod
    monkeypatch.setattr(router_mod, "LLMRouter", _Router)
    with pytest.raises(lc.ReplayEnvironmentError):
        lc.LLMCache(mode="replay", cache_dir=cache_dir).install()


def test_an_ambiguous_alias_is_left_out(tmp_path):
    entries = [{"exact": "k1", "alias": "a", "native": True, "hit": True},
               {"exact": "k2", "alias": "a", "native": True, "hit": True},
               {"exact": "k3", "alias": "b", "native": True, "hit": True},
               {"exact": "k4", "alias": "c", "native": False, "hit": True},
               {"exact": "k5", "alias": "d", "native": None, "hit": True},
               {"exact": "k6", "alias": "e", "native": True, "hit": False}]
    index, report = lc.build_alias_index(entries)
    assert index == {"b": "k3"}
    assert report["ambiguous_aliases"] == 1 and report["ocr_or_unknown"] == 2


def test_alias_only_mode_skips_the_exact_lookup(cache_dir, monkeypatch):
    """DOCAGENT_REPLAY_ALIAS_ONLY=1 proves the alias path on the recording
    machine: an indexed request is served by alias even when its exact key
    would hit."""
    monkeypatch.setattr(lc, "render_fingerprint", lambda: "recorded-elsewhere")
    monkeypatch.setenv("DOCAGENT_REPLAY_ALIAS_ONLY", "1")
    c = _install(cache_dir, monkeypatch)
    try:
        resp = _Router().extract(image_b64=[_jpeg(40, 30, 10)], **REQ)
    finally:
        c.uninstall()
    assert resp.success and c.stats["alias_hits"] == 1 and c.stats["hits"] == 0


def test_the_runner_refuses_to_score_a_replay_miss():
    src = (bs.REPO_DIR / "tests" / "harness" / "runner.py").read_text(encoding="utf-8")
    assert "replay_misses_are_fatal(" in src


def test_replay_misses_are_fatal():
    c = lc.LLMCache(mode="replay")
    c.stats["misses"] = 2
    with pytest.raises(SystemExit):
        lc.replay_misses_are_fatal(c)
    c.stats["misses"] = 0
    lc.replay_misses_are_fatal(c)


def test_the_committed_index_matches_the_committed_cache():
    """Every alias in the committed index points at an entry that exists and
    carries that exact key."""
    index = lc.load_alias_index(bs.CACHE_DIR)
    assert index, "tests/llm_cache/_alias_index.json is missing or empty"
    c = lc.LLMCache(mode="replay")
    missing = [k for k in index.values() if c._load(k) is None]
    assert not missing, f"{len(missing)} aliases point at no cache entry"


@pytest.mark.parametrize("exc", [lc.CacheMiss("miss"),
                                 lc.ReplayEnvironmentError("render")])
def test_a_replay_failure_is_not_swallowed_by_the_engine(exc, monkeypatch):
    """The engine catches `Exception` around every model call and turns it
    into a failed call — which a test or the harness then scores as a wrong
    answer. A replay miss or render mismatch must escape that."""
    from types import SimpleNamespace
    import extractor
    monkeypatch.setattr(extractor.time, "sleep", lambda s: None)

    def boom(**kw):
        raise exc
    orch = SimpleNamespace(llm=SimpleNamespace(extract=boom))
    with pytest.raises(type(exc)):
        extractor._llm_json(orch, "p", "s", text="t")
