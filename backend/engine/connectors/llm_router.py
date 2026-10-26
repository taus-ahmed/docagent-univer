"""
DocAgent - LLM Router
Sends each request to the configured providers in order: PRIMARY_LLM first,
then each name in LLM_FALLBACKS, until one succeeds.

Gemini is the only provider implemented, and the fallback list is empty by
default. A provider is a class implementing `connectors.base.LLMProvider`,
registered in PROVIDERS under the name the settings use.
"""
import logging
from typing import Callable, Optional

from connectors.base import LLMProvider, LLMResponse
from connectors.gemini_client import GeminiClient
from config import settings
from log_safety import exc_brief

logger = logging.getLogger("docagent.llm_router")


def _gemini() -> Optional[LLMProvider]:
    if not settings.GEMINI_API_KEY:
        return None
    return GeminiClient(api_key=settings.GEMINI_API_KEY)


#: name → factory returning a ready provider, or None when it is not configured
#: (no API key). The names are what PRIMARY_LLM and LLM_FALLBACKS hold.
def _stub() -> Optional[LLMProvider]:
    # DEV ONLY (connectors/stub_client.py). Refused at startup outside
    # ENVIRONMENT=development; never chosen unless named explicitly.
    from connectors.stub_client import StubClient
    return StubClient()


PROVIDERS: dict[str, Callable[[], Optional[LLMProvider]]] = {
    "gemini": _gemini,
    "stub": _stub,
}

#: providers that are only ever used when NAMED: never a fallback default
EXPLICIT_ONLY = {"stub"}


def provider_order() -> list[str]:
    """PRIMARY_LLM, then LLM_FALLBACKS (comma-separated), without repeats."""
    names = [getattr(settings, "PRIMARY_LLM", "gemini") or "gemini"]
    names += str(getattr(settings, "LLM_FALLBACKS", "") or "").split(",")
    order: list[str] = []
    for n in (n.strip().lower() for n in names):
        if n and n not in order:
            order.append(n)
    return order


class LLMRouter:
    """Routing between configured LLM providers with fallback in order."""

    def __init__(self):
        self.providers: list[tuple[str, LLMProvider]] = []
        names = provider_order()
        unknown = [n for n in names if n not in PROVIDERS]
        if unknown:
            logger.warning(f"Unknown LLM provider(s) ignored: {', '.join(unknown)}; "
                           f"implemented: {', '.join(PROVIDERS)}")
        named = [n for n in names if n in PROVIDERS]
        defaults = [n for n in PROVIDERS if n not in EXPLICIT_ONLY]
        for name in named or defaults:
            try:
                provider = PROVIDERS[name]()
            except Exception as e:
                logger.warning(f"{name} init failed: {exc_brief(e)}")
                continue
            if provider is not None:
                self.providers.append((name, provider))
        self.stats = {f"{name}_calls": 0 for name in PROVIDERS}
        self.stats["failures"] = 0

        if not self.providers:
            raise ValueError("No LLM provider available. Set GEMINI_API_KEY.")

    @property
    def primary(self) -> LLMProvider:
        return self.providers[0][1]

    # ── Classification ────────────────────────────────────────────────────────

    def classify(self, text: str = "", image_b64: str = "",
                 prompt: str = "") -> LLMResponse:
        use_vision = bool(image_b64) and not text
        for name, provider in self.providers:
            try:
                result = (
                    provider.classify_document_vision(image_b64, prompt)
                    if use_vision else
                    provider.classify_document(text, prompt)
                )
                if result.success:
                    self._track(name)
                    return result
            except Exception as e:
                logger.warning(f"Classification {name} failed: {exc_brief(e)}")
        self.stats["failures"] += 1
        return LLMResponse(raw_text="", success=False,
                           error="All providers failed for classification")

    # ── Extraction ────────────────────────────────────────────────────────────

    def extract(self, text: str = "", image_b64: str = "",
                prompt: str = "",
                system_instruction: str = "", model: str = None,
                temperature: float = 0.1) -> LLMResponse:
        """
        Route an extraction request, falling back in order.

        system_instruction: the registry expert persona (stable, doc-type specific).
          Passed to Gemini as system_instruction — billed at reduced rate and
          cached server-side. Same for all documents of the same type in a batch.

        prompt: template fields + doc text (variable per document).

        model: optional Gemini model override tried FIRST (e.g. "gemini-2.5-flash"
          to pin accuracy-critical calls to a stronger tier than the default -lite).

        temperature: sampling temperature. Extraction calls keep the 0.1 default;
          shape INFERENCE passes 0, because it decides what the columns are
          CALLED and a near-tie there ("Doc No" vs "Document Number") renames a
          column between runs. A fallback provider may select its own; if a run
          ever falls back mid-batch the naming can still move.
        """
        use_vision = bool(image_b64) and not text

        for name, provider in self.providers:
            try:
                result = (
                    provider.extract_data_vision(
                        image_b64, prompt, system_instruction, model=model,
                        temperature=temperature)
                    if use_vision else
                    provider.extract_data(
                        text, prompt, system_instruction, model=model,
                        temperature=temperature)
                )

                if result.success:
                    self._track(name)
                    return result

                logger.warning(f"Extraction {name} failed (provider error, {len(result.error or '')} chars, not logged)")

            except Exception as e:
                logger.warning(f"Extraction {name} exception: {exc_brief(e)}")

        self.stats["failures"] += 1
        return LLMResponse(raw_text="", success=False,
                           error="All providers failed for extraction")

    def _track(self, name: str):
        self.stats[f"{name}_calls"] = self.stats.get(f"{name}_calls", 0) + 1
