"""The provider seam: PRIMARY_LLM first, then LLM_FALLBACKS, in order.

Gemini is the only provider implemented. These tests use stub providers, so
no network call is made.
"""
import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

from connectors import llm_router  # noqa: E402
from connectors.base import LLMResponse  # noqa: E402
from connectors.gemini_client import GeminiClient  # noqa: E402


class Stub:
    def __init__(self, name, ok=True, raises=False):
        self.name, self.ok, self.raises, self.calls = name, ok, raises, []

    def _answer(self, *a, **k):
        self.calls.append((a, k))
        if self.raises:
            raise RuntimeError(f"{self.name} down")
        return LLMResponse(raw_text=self.name, success=self.ok,
                           error="" if self.ok else f"{self.name} failed")

    classify_document = classify_document_vision = _answer
    extract_data = extract_data_vision = _answer


@pytest.fixture
def providers(monkeypatch, replay_cache):
    # The session's replay cache wraps LLMRouter.extract/classify; these tests
    # exercise the router itself, so they run on its own methods.
    monkeypatch.setattr(llm_router.LLMRouter, "extract", replay_cache._orig["extract"])
    monkeypatch.setattr(llm_router.LLMRouter, "classify", replay_cache._orig["classify"])

    def install(primary, fallbacks="", **stubs):
        monkeypatch.setattr(llm_router.settings, "PRIMARY_LLM", primary)
        monkeypatch.setattr(llm_router.settings, "LLM_FALLBACKS", fallbacks,
                            raising=False)
        monkeypatch.setattr(llm_router, "PROVIDERS",
                            {n: (lambda s=s: s) for n, s in stubs.items()})
        return llm_router.LLMRouter()
    return install


def test_default_is_gemini_only_with_no_fallback(monkeypatch):
    monkeypatch.setattr(llm_router.settings, "PRIMARY_LLM", "gemini")
    monkeypatch.setattr(llm_router.settings, "LLM_FALLBACKS", "", raising=False)
    r = llm_router.LLMRouter()
    assert [n for n, _ in r.providers] == ["gemini"]
    assert isinstance(r.primary, GeminiClient)
    assert list(llm_router.PROVIDERS) == ["gemini"]


def test_primary_receives_every_argument_unchanged(providers):
    a = Stub("a")
    r = providers("a", a=a)
    out = r.extract(text="doc", prompt="p", system_instruction="si",
                    model="m", temperature=0)
    assert out.raw_text == "a" and r.stats["a_calls"] == 1
    assert a.calls == [(("doc", "p", "si"), {"model": "m", "temperature": 0})]
    r.extract(image_b64=["i1", "i2"], prompt="p")
    assert a.calls[-1] == ((["i1", "i2"], "p", ""),
                           {"model": None, "temperature": 0.1})


def test_fallbacks_are_tried_in_order(providers):
    a, b, c = Stub("a", ok=False), Stub("b", raises=True), Stub("c")
    r = providers("a", " B , c ", a=a, b=b, c=c)
    assert [n for n, _ in r.providers] == ["a", "b", "c"]
    assert r.extract(text="t", prompt="p").raw_text == "c"
    assert (len(a.calls), len(b.calls), len(c.calls)) == (1, 1, 1)
    assert r.classify(text="t", prompt="p").raw_text == "c"


def test_all_failing_is_a_named_failure(providers):
    r = providers("a", a=Stub("a", ok=False))
    out = r.extract(text="t", prompt="p")
    assert not out.success and out.error == "All providers failed for extraction"
    assert r.stats["failures"] == 1


def test_unknown_names_are_ignored_not_fatal(providers, caplog):
    a = Stub("a")
    r = providers("groq", "xai", a=a)
    assert [n for n, _ in r.providers] == ["a"]
    assert "groq" in caplog.text and "xai" in caplog.text


def test_no_configured_provider_raises(providers):
    with pytest.raises(ValueError, match="GEMINI_API_KEY"):
        providers("a", a=None)


def test_no_groq_anywhere():
    import importlib.util
    assert importlib.util.find_spec("connectors.groq_client") is None
