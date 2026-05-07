"""
DocAgent — Gemini API Client
Robust JSON parsing, markdown stripping, retry on parse failure.
"""
import json
import time
import base64
import re
from typing import Optional
from dataclasses import dataclass
from config import settings
from connectors.groq_client import LLMResponse


def _parse_json_robust(raw: str) -> Optional[dict]:
    """
    Parse JSON from LLM response robustly.
    Handles: markdown fences, leading text, trailing text, single quotes.
    """
    if not raw:
        return None

    text = raw.strip()

    # Strategy 1: strip markdown fences
    # ```json ... ``` or ``` ... ```
    fence_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Strategy 2: find the first { and last } and extract
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1 and end > start:
        candidate = text[start:end + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # Strategy 3: try the full stripped text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strategy 4: fix common LLM JSON mistakes
    # Replace single quotes with double quotes (cautiously)
    try:
        fixed = re.sub(r"'([^']*)'", r'"\1"', text)
        start = fixed.find('{')
        end = fixed.rfind('}')
        if start != -1 and end != -1:
            return json.loads(fixed[start:end + 1])
    except Exception:
        pass

    print(f"[GEMINI] JSON parse failed. Raw response (first 500 chars): {raw[:500]}", flush=True)
    return None


class GeminiClient:
    """Google Gemini API wrapper — primary provider."""

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or settings.GEMINI_API_KEY
        self._client = None
        self._model = None

    def _ensure_client(self):
        if self._client is None:
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            self._client = genai
            model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')
            self._model = genai.GenerativeModel(model_name)
            print(f"[GEMINI] Initialized with model: {model_name}", flush=True)

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
        # Append strict JSON instruction at the end to override any tendency
        # to wrap in markdown
        strict_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Your response must be ONLY the raw JSON object. "
            "Do NOT wrap in ```json``` or any markdown. "
            "Start your response with { and end with }. Nothing else."
        )
        return self._text_completion(prompt=strict_prompt)

    def extract_data_vision(self, image_b64: str, prompt: str) -> LLMResponse:
        self._ensure_client()
        strict_prompt = (
            f"{prompt}\n\n"
            "IMPORTANT: Your response must be ONLY the raw JSON object. "
            "Do NOT wrap in ```json``` or any markdown. "
            "Start your response with { and end with }. Nothing else."
        )
        return self._vision_completion(prompt=strict_prompt, image_b64=image_b64)

    def _text_completion(self, prompt: str) -> LLMResponse:
        start = time.time()
        model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')
        try:
            response = self._model.generate_content(
                prompt,
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 8192,
                    "response_mime_type": "application/json",
                },
            )
            raw = response.text
            print(f"[GEMINI] Text response length: {len(raw)} chars", flush=True)
            parsed = _parse_json_robust(raw)

            if parsed is None:
                # Retry once with even stricter instruction
                print("[GEMINI] First parse failed, retrying with stricter prompt", flush=True)
                retry_prompt = (
                    "Return ONLY a JSON object. No explanation. No markdown. "
                    "Just the raw JSON starting with { and ending with }.\n\n"
                    f"Original task:\n{prompt[:2000]}"
                )
                retry_response = self._model.generate_content(
                    retry_prompt,
                    generation_config={
                        "temperature": 0.0,
                        "max_output_tokens": 4096,
                        "response_mime_type": "application/json",
                    },
                )
                raw = retry_response.text
                parsed = _parse_json_robust(raw)

            return LLMResponse(
                raw_text=raw,
                parsed_json=parsed,
                model_used=model_name,
                latency_ms=(time.time() - start) * 1000,
                success=parsed is not None,
                error="" if parsed else f"JSON parse failed. Response: {raw[:200]}",
            )
        except Exception as e:
            print(f"[GEMINI] Text completion error: {e}", flush=True)
            return LLMResponse(
                raw_text="", success=False,
                error=f"Gemini error: {str(e)}",
                model_used=model_name,
                latency_ms=(time.time() - start) * 1000,
            )

    def _vision_completion(self, prompt: str, image_b64: str) -> LLMResponse:
        start = time.time()
        model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')
        try:
            import PIL.Image
            import io as _io

            image_bytes = base64.b64decode(image_b64)
            image = PIL.Image.open(_io.BytesIO(image_bytes))

            print(f"[GEMINI] Vision request: image {image.size}, prompt {len(prompt)} chars", flush=True)

            response = self._model.generate_content(
                [prompt, image],
                generation_config={
                    "temperature": 0.1,
                    "max_output_tokens": 8192,
                    "response_mime_type": "application/json",
                },
            )
            raw = response.text
            print(f"[GEMINI] Vision response length: {len(raw)} chars", flush=True)
            parsed = _parse_json_robust(raw)

            if parsed is None:
                print("[GEMINI] Vision parse failed, retrying text-only", flush=True)
                # Fallback: retry without image, just text
                retry_prompt = (
                    "Return ONLY a JSON object. No explanation. No markdown.\n\n"
                    f"{prompt[:2000]}"
                )
                retry_response = self._model.generate_content(
                    retry_prompt,
                    generation_config={
                        "temperature": 0.0,
                        "max_output_tokens": 4096,
                        "response_mime_type": "application/json",
                    },
                )
                raw = retry_response.text
                parsed = _parse_json_robust(raw)

            return LLMResponse(
                raw_text=raw,
                parsed_json=parsed,
                model_used=model_name,
                latency_ms=(time.time() - start) * 1000,
                success=parsed is not None,
                error="" if parsed else f"Vision JSON parse failed. Response: {raw[:200]}",
            )
        except Exception as e:
            print(f"[GEMINI] Vision error: {e}", flush=True)
            return LLMResponse(
                raw_text="", success=False,
                error=f"Gemini vision error: {str(e)}",
                model_used=model_name,
                latency_ms=(time.time() - start) * 1000,
            )
