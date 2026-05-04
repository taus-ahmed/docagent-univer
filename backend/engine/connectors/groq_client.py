"""
DocAgent — Groq API Client
Handles all communication with Groq's API.
Includes rate limiting, retry logic, and structured response parsing.
"""

import json
import time
import base64
import logging
from typing import Optional
from dataclasses import dataclass

from groq import Groq

from config import settings

logger = logging.getLogger("docagent.groq")


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


class GroqClient:
    """Groq API wrapper with rate limiting and retry."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or settings.GROQ_API_KEY
        if not self.api_key:
            raise ValueError("GROQ_API_KEY is required. Set it in .env file.")
        self.client = Groq(api_key=self.api_key)
        self._last_request_time = 0
        self._min_interval = settings.RATE_LIMIT_DELAY

    def _rate_limit(self):
        """Simple rate limiter to stay within Groq's free tier."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_time = time.time()

    def classify_document(self, text: str, prompt: str) -> LLMResponse:
        """Pass 1: Classify a document using text content.
        Uses the text model (GROQ_EXTRACTION_MODEL), NOT the vision model."""
        return self._text_completion(
            system_prompt=prompt,
            user_content=f"Document content:\n\n{text[:8000]}",
            model=settings.GROQ_EXTRACTION_MODEL,
        )

    def classify_document_vision(self, image_b64: str, prompt: str) -> LLMResponse:
        """Pass 1: Classify a document using image (for scanned docs)."""
        return self._vision_completion(
            system_prompt=prompt,
            image_b64=image_b64,
            user_text="Classify this document.",
            model=settings.GROQ_VISION_MODEL,
        )

    def extract_data(self, text: str, prompt: str) -> LLMResponse:
        """Pass 2: Extract structured data from document text."""
        return self._text_completion(
            system_prompt=prompt,
            user_content=f"Document content:\n\n{text}",
            model=settings.GROQ_EXTRACTION_MODEL,
        )

    def extract_data_vision(self, image_b64: str, prompt: str) -> LLMResponse:
        """Pass 2: Extract structured data from document image."""
        return self._vision_completion(
            system_prompt=prompt,
            image_b64=image_b64,
            user_text="Extract all data from this document image according to the schema.",
            model=settings.GROQ_VISION_MODEL,
        )

    def auto_detect_schema(self, text: str = "", image_b64: str = "", prompt: str = "") -> LLMResponse:
        """Detect what fields are extractable from a document."""
        if image_b64:
            return self._vision_completion(
                system_prompt=prompt,
                image_b64=image_b64,
                user_text="Analyze this document and identify all extractable fields.",
                model=settings.GROQ_VISION_MODEL,
            )
        return self._text_completion(
            system_prompt=prompt,
            user_content=f"Analyze this document:\n\n{text[:8000]}",
            model=settings.GROQ_EXTRACTION_MODEL,
        )

    def _text_completion(self, system_prompt: str, user_content: str, model: str) -> LLMResponse:
        """Execute a text-only completion."""
        self._rate_limit()
        start = time.time()

        for attempt in range(settings.MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                    response_format={"type": "json_object"},
                )

                raw = response.choices[0].message.content
                latency = (time.time() - start) * 1000
                tokens = response.usage.total_tokens if response.usage else 0
                parsed = _parse_json_response(raw)

                return LLMResponse(
                    raw_text=raw, parsed_json=parsed, model_used=model,
                    tokens_used=tokens, latency_ms=latency,
                    success=parsed is not None,
                    error="" if parsed else "Failed to parse JSON response",
                )

            except Exception as e:
                logger.warning(f"Text API attempt {attempt+1}/{settings.MAX_RETRIES} with {model}: {e}")
                if attempt < settings.MAX_RETRIES - 1:
                    time.sleep((attempt + 1) * 3)
                    continue
                return LLMResponse(
                    raw_text="", success=False,
                    error=f"API error after {settings.MAX_RETRIES} retries: {str(e)}",
                    model_used=model, latency_ms=(time.time() - start) * 1000,
                )

    def _vision_completion(self, system_prompt: str, image_b64: str, user_text: str, model: str) -> LLMResponse:
        """Execute a vision completion with an image."""
        self._rate_limit()
        start = time.time()

        for attempt in range(settings.MAX_RETRIES):
            try:
                response = self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "image_url",
                                    "image_url": {
                                        "url": f"data:image/jpeg;base64,{image_b64}",
                                    },
                                },
                                {"type": "text", "text": user_text},
                            ],
                        },
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )

                raw = response.choices[0].message.content
                latency = (time.time() - start) * 1000
                tokens = response.usage.total_tokens if response.usage else 0
                parsed = _parse_json_response(raw)

                return LLMResponse(
                    raw_text=raw, parsed_json=parsed, model_used=model,
                    tokens_used=tokens, latency_ms=latency,
                    success=parsed is not None,
                    error="" if parsed else "Failed to parse JSON from vision response",
                )

            except Exception as e:
                logger.warning(f"Vision API attempt {attempt+1}/{settings.MAX_RETRIES} with {model}: {e}")
                if attempt < settings.MAX_RETRIES - 1:
                    time.sleep((attempt + 1) * 3)
                    continue
                return LLMResponse(
                    raw_text="", success=False,
                    error=f"Vision API error after {settings.MAX_RETRIES} retries: {str(e)}",
                    model_used=model, latency_ms=(time.time() - start) * 1000,
                )


def _parse_json_response(text: str) -> Optional[dict]:
    """Robustly parse JSON from LLM response, handling common issues."""
    if not text:
        return None

    text = text.strip()

    # Remove markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in the text
    start = text.find("{")
    end = text.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end])
        except json.JSONDecodeError:
            pass

    return None