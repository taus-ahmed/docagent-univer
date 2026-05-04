"""
DocAgent — LLM Router
Routes requests to the best available LLM provider.
Handles fallback: Groq → Gemini → Error
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

        groq_key = settings.GROQ_API_KEY
        gemini_key = settings.GEMINI_API_KEY

        if groq_key:
            try:
                self._groq = GroqClient(api_key=groq_key)
            except Exception as e:
                logger.warning(f"Groq init failed: {e}")

        if gemini_key:
            try:
                self._gemini = GeminiClient(api_key=gemini_key)
            except Exception as e:
                logger.warning(f"Gemini init failed: {e}")

        if not self._groq and not self._gemini:
            raise ValueError(
                "No LLM provider available. Set GROQ_API_KEY or GEMINI_API_KEY in .env"
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

    def classify(self, text: str = "", image_b64: str = "", prompt: str = "") -> LLMResponse:
        """Route a classification request with fallback."""
        use_vision = bool(image_b64) and not text

        for name, provider in [("primary", self.primary), ("fallback", self.fallback)]:
            if provider is None:
                continue
            try:
                if use_vision:
                    result = provider.classify_document_vision(image_b64, prompt)
                else:
                    result = provider.classify_document(text, prompt)
                if result.success:
                    self._track(provider)
                    return result
            except Exception as e:
                logger.warning(f"Classification {name} failed: {e}")
                continue

        self.stats["failures"] += 1
        return LLMResponse(raw_text="", success=False, error="All providers failed for classification")

    def extract(self, text: str = "", image_b64: str = "", prompt: str = "") -> LLMResponse:
        """Route an extraction request with fallback."""
        use_vision = bool(image_b64) and not text

        for name, provider in [("primary", self.primary), ("fallback", self.fallback)]:
            if provider is None:
                continue
            try:
                if use_vision:
                    result = provider.extract_data_vision(image_b64, prompt)
                else:
                    result = provider.extract_data(text, prompt)
                if result.success:
                    self._track(provider)
                    return result
            except Exception as e:
                logger.warning(f"Extraction {name} failed: {e}")
                continue

        self.stats["failures"] += 1
        return LLMResponse(raw_text="", success=False, error="All providers failed for extraction")

    def _track(self, provider):
        if isinstance(provider, GroqClient):
            self.stats["groq_calls"] += 1
        else:
            self.stats["gemini_calls"] += 1