"""
DocAgent — Gemini API Client (Fallback)
Used when Groq is rate-limited or unavailable.
"""

import json
import time
import base64
from typing import Optional
from dataclasses import dataclass

from backend.engine.config import settings
from connectors.groq_client import LLMResponse, _parse_json_response


class GeminiClient:
    """Google Gemini API wrapper — fallback provider."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self._client = None
        self._model = None

    def _ensure_client(self):
        if self._client is None:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._client = genai
            self._model = genai.GenerativeModel(settings.GEMINI_MODEL)

    def classify_document(self, text: str, prompt: str) -> LLMResponse:
        self._ensure_client()
        return self._text_completion(
            prompt=f"{prompt}\n\nDocument content:\n\n{text[:8000]}",
        )

    def classify_document_vision(self, image_b64: str, prompt: str) -> LLMResponse:
        self._ensure_client()
        return self._vision_completion(
            prompt=f"{prompt}\n\nClassify this document.",
            image_b64=image_b64,
        )

    def extract_data(self, text: str, prompt: str) -> LLMResponse:
        self._ensure_client()
        return self._text_completion(
            prompt=f"{prompt}\n\nDocument content:\n\n{text}",
        )

    def extract_data_vision(self, image_b64: str, prompt: str) -> LLMResponse:
        self._ensure_client()
        return self._vision_completion(
            prompt=f"{prompt}\n\nExtract all data from this document image.",
            image_b64=image_b64,
        )

    def _text_completion(self, prompt: str) -> LLMResponse:
        start = time.time()
        try:
            response = self._model.generate_content(
                prompt,
                generation_config={"temperature": 0.1, "max_output_tokens": 4096},
            )
            raw = response.text
            parsed = _parse_json_response(raw)
            return LLMResponse(
                raw_text=raw,
                parsed_json=parsed,
                model_used=settings.GEMINI_MODEL,
                latency_ms=(time.time() - start) * 1000,
                success=parsed is not None,
                error="" if parsed else "Failed to parse JSON",
            )
        except Exception as e:
            return LLMResponse(
                raw_text="", success=False,
                error=f"Gemini error: {str(e)}",
                model_used=settings.GEMINI_MODEL,
                latency_ms=(time.time() - start) * 1000,
            )

    def _vision_completion(self, prompt: str, image_b64: str) -> LLMResponse:
        start = time.time()
        try:
            import PIL.Image
            import io
            image_bytes = base64.b64decode(image_b64)
            image = PIL.Image.open(io.BytesIO(image_bytes))

            response = self._model.generate_content(
                [prompt, image],
                generation_config={"temperature": 0.1, "max_output_tokens": 4096},
            )
            raw = response.text
            parsed = _parse_json_response(raw)
            return LLMResponse(
                raw_text=raw,
                parsed_json=parsed,
                model_used=settings.GEMINI_MODEL,
                latency_ms=(time.time() - start) * 1000,
                success=parsed is not None,
                error="" if parsed else "Failed to parse JSON",
            )
        except Exception as e:
            return LLMResponse(
                raw_text="", success=False,
                error=f"Gemini vision error: {str(e)}",
                model_used=settings.GEMINI_MODEL,
                latency_ms=(time.time() - start) * 1000,
            )
