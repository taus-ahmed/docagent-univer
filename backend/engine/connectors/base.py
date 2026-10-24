"""
DocAgent — the provider seam.

Every model call returns an `LLMResponse`, whichever provider answered it, and
every provider offers the four calls `LLMRouter` makes. Gemini is the only
provider implemented; a second one is added by implementing `LLMProvider` and
registering a factory in `llm_router.PROVIDERS`.
"""
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    raw_text: str
    parsed_json: Optional[dict] = None
    model_used: str = ""
    tokens_used: int = 0
    latency_ms: float = 0
    success: bool = True
    error: str = ""


class LLMProvider(Protocol):
    """What the router needs from a provider. A call never raises for a
    provider-side failure: it returns `success=False` with the error."""

    def classify_document(self, text: str, prompt: str) -> LLMResponse: ...

    def classify_document_vision(self, image_b64: str,
                                 prompt: str) -> LLMResponse: ...

    def extract_data(self, text: str, prompt: str,
                     system_instruction: str = "", model: str = None,
                     temperature: float = 0.1) -> LLMResponse: ...

    def extract_data_vision(self, image_b64, prompt: str,
                            system_instruction: str = "", model: str = None,
                            temperature: float = 0.1) -> LLMResponse: ...
