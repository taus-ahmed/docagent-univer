"""
DocAgent - LLM Router
Routes requests to the best available LLM provider.
Primary: Gemini (when PRIMARY_LLM=gemini)
Fallback: Groq
"""
import logging
from typing import Optional
from connectors.groq_client import GroqClient, LLMResponse
from connectors.gemini_client import GeminiClient
from config import settings

logger = logging.getLogger("docagent.llm_router")


class LLMRouter:
    """Intelligent routing between LLM providers with automatic fallback."""

    def __init__(self):
        self._groq: Optional[GroqClient] = None
        self._gemini: Optional[GeminiClient] = None
        self.stats = {"groq_calls": 0, "gemini_calls": 0, "failures": 0}

        if settings.GROQ_API_KEY:
            try:
                self._groq = GroqClient(api_key=settings.GROQ_API_KEY)
            except Exception as e:
                logger.warning(f"Groq init failed: {e}")

        if settings.GEMINI_API_KEY:
            try:
                self._gemini = GeminiClient(api_key=settings.GEMINI_API_KEY)
            except Exception as e:
                logger.warning(f"Gemini init failed: {e}")

        if not self._groq and not self._gemini:
            raise ValueError(
                "No LLM provider available. Set GROQ_API_KEY or GEMINI_API_KEY."
            )

    @property
    def primary(self):
        if settings.PRIMARY_LLM == "gemini" and self._gemini:
            return self._gemini
        return self._groq or self._gemini

    @property
    def fallback(self):
        if settings.PRIMARY_LLM == "gemini":
            return self._groq
        return self._gemini

    # ── Classification ────────────────────────────────────────────────────────

    def classify(self, text: str = "", image_b64: str = "",
                 prompt: str = "") -> LLMResponse:
        use_vision = bool(image_b64) and not text
        for name, provider in [("primary", self.primary),
                                ("fallback", self.fallback)]:
            if provider is None:
                continue
            try:
                result = (
                    provider.classify_document_vision(image_b64, prompt)
                    if use_vision else
                    provider.classify_document(text, prompt)
                )
                if result.success:
                    self._track(provider)
                    return result
            except Exception as e:
                logger.warning(f"Classification {name} failed: {e}")
        self.stats["failures"] += 1
        return LLMResponse(raw_text="", success=False,
                           error="All providers failed for classification")

    # ── Extraction ────────────────────────────────────────────────────────────

    def extract(self, text: str = "", image_b64: str = "",
                prompt: str = "",
                system_instruction: str = "") -> LLMResponse:
        """
        Route an extraction request with automatic fallback.

        system_instruction: the registry expert persona (stable, doc-type specific).
          Passed to Gemini as system_instruction — billed at reduced rate and
          cached server-side. Same for all documents of the same type in a batch.
          Groq receives it prepended to the prompt (Groq has no system role split).

        prompt: template fields + doc text (variable per document).
        """
        use_vision = bool(image_b64) and not text

        for name, provider in [("primary", self.primary),
                                ("fallback", self.fallback)]:
            if provider is None:
                continue
            try:
                if isinstance(provider, GeminiClient):
                    # Gemini: pass system_instruction separately for token savings
                    result = (
                        provider.extract_data_vision(
                            image_b64, prompt, system_instruction)
                        if use_vision else
                        provider.extract_data(
                            text, prompt, system_instruction)
                    )
                else:
                    # Groq / other providers: prepend system_instruction to prompt
                    # so they receive full context even without native si support
                    full_prompt = (
                        f"{system_instruction}\n\n{prompt}"
                        if system_instruction else prompt
                    )
                    result = (
                        provider.extract_data_vision(image_b64, full_prompt)
                        if use_vision else
                        provider.extract_data(text, full_prompt)
                    )

                if result.success:
                    self._track(provider)
                    return result

                logger.warning(f"Extraction {name} failed: {result.error[:100]}")

            except Exception as e:
                logger.warning(f"Extraction {name} exception: {e}")

        self.stats["failures"] += 1
        return LLMResponse(raw_text="", success=False,
                           error="All providers failed for extraction")

    def _track(self, provider):
        if isinstance(provider, GroqClient):
            self.stats["groq_calls"] += 1
        else:
            self.stats["gemini_calls"] += 1
