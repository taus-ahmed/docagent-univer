"""
DocAgent — Gemini API Client (REST API Direct)

Uses the Gemini REST API directly instead of the google-generativeai SDK.
This completely bypasses model naming issues with the v1beta SDK.

Benefits:
  - Full control over API version (v1 instead of v1beta)
  - No SDK version compatibility issues
  - Exact token counting from response metadata
  - system_instruction passed as separate field for token efficiency
  - response_mime_type=application/json forces clean JSON output

Cost reference (gemini-1.5-flash):
  Input:  $0.075 per 1M tokens
  Output: $0.30  per 1M tokens
  ~1,200 tokens per doc = $0.00015 per document
  $10 covers ~65,000 documents
"""
import json
import time
import base64
import urllib.request
import urllib.error
from typing import Optional
from config import settings
from connectors.groq_client import LLMResponse


def _parse_json_robust(raw: str) -> Optional[dict]:
    """Parse JSON from LLM response — strips markdown fences, finds {…}."""
    import re
    if not raw:
        return None
    text = raw.strip()
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()
    s, e = text.find('{'), text.rfind('}')
    if s != -1 and e > s:
        try:
            return json.loads(text[s:e + 1])
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    print(f"[GEMINI] JSON parse failed. Raw[:300]: {raw[:300]}", flush=True)
    return None


def _log_tokens(label: str, inp: int, out: int) -> int:
    total = inp + out
    cost  = (inp / 1_000_000) * 0.075 + (out / 1_000_000) * 0.30
    print(f"[GEMINI] {label}: {inp} in + {out} out = {total} | ${cost:.5f}",
          flush=True)
    return total


class GeminiClient:
    """Gemini client using direct REST API — zero SDK dependency issues."""

    # Model candidates tried in order until one works
    MODEL_CANDIDATES = [
        "gemini-1.5-flash",
        "gemini-1.5-flash-001",
        "gemini-1.5-flash-002",
        "gemini-1.5-flash-8b",
        "gemini-1.0-pro",
    ]

    def __init__(self, api_key: str = ""):
        self.api_key     = api_key or settings.GEMINI_API_KEY
        self._model_name = getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')
        # Strip models/ prefix if present — we build the URL ourselves
        self._model_name = self._model_name.replace('models/', '').strip()
        self._working_model: Optional[str] = None  # cached after first success
        print(f"[GEMINI] ready: {self._model_name} (REST API)", flush=True)

    def _call_rest(self, model: str, prompt: str,
                   system_instruction: str = "",
                   temperature: float = 0.1,
                   max_tokens: int = 8192) -> tuple:
        """
        Call Gemini REST API directly.
        Returns (raw_text, input_tokens, output_tokens) or raises.
        """
        url = (f"https://generativelanguage.googleapis.com/v1/models/"
               f"{model}:generateContent?key={self.api_key}")

        body: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature":      temperature,
                "maxOutputTokens":  max_tokens,
                "responseMimeType": "application/json",
            },
        }

        # Pass system instruction as separate field for token efficiency
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        data = json.dumps(body).encode('utf-8')
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=60) as resp:
            result   = json.loads(resp.read())
            raw      = result["candidates"][0]["content"]["parts"][0]["text"]
            usage    = result.get("usageMetadata", {})
            inp_tok  = usage.get("promptTokenCount", 0)
            out_tok  = usage.get("candidatesTokenCount", 0)
            return raw, inp_tok, out_tok

    def _call_with_fallback(self, prompt: str,
                             system_instruction: str = "",
                             temperature: float = 0.1,
                             max_tokens: int = 8192,
                             label: str = "text") -> tuple:
        """
        Try the configured model first, then fall back through candidates.
        Returns (raw, total_tokens, model_used).
        """
        # If we already found a working model, use it directly
        candidates = (
            [self._working_model] + self.MODEL_CANDIDATES
            if self._working_model else
            [self._model_name] + self.MODEL_CANDIDATES
        )
        # Deduplicate while preserving order
        seen, ordered = set(), []
        for m in candidates:
            if m and m not in seen:
                seen.add(m); ordered.append(m)

        for model in ordered:
            try:
                raw, inp, out = self._call_rest(
                    model, prompt, system_instruction, temperature, max_tokens
                )
                tok = _log_tokens(f"{label}:{model}", inp, out)
                self._working_model = model  # cache success
                return raw, tok, model
            except Exception as e:
                err = str(e)
                print(f"[GEMINI] {model} failed: {err[:120]}", flush=True)
                # Don't retry on auth errors
                if "API_KEY" in err.upper() or "403" in err:
                    break
                continue

        raise RuntimeError("All Gemini model candidates failed")

    # ── Public API ────────────────────────────────────────────────────────────

    def classify_document(self, text: str, prompt: str) -> LLMResponse:
        return self._text_call(
            f"{prompt}\n\nDocument:\n{text[:4000]}"
        )

    def classify_document_vision(self, image_b64: str, prompt: str) -> LLMResponse:
        return self._vision_call(
            f"{prompt}\n\nClassify this document.", image_b64
        )

    def extract_data(self, text: str, prompt: str,
                     system_instruction: str = "") -> LLMResponse:
        return self._text_call(prompt, system_instruction)

    def extract_data_vision(self, image_b64: str, prompt: str,
                             system_instruction: str = "") -> LLMResponse:
        return self._vision_call(prompt, image_b64, system_instruction)

    # ── Core calls ────────────────────────────────────────────────────────────

    def _text_call(self, prompt: str,
                   system_instruction: str = "") -> LLMResponse:
        t0 = time.time()
        try:
            raw, tok, model = self._call_with_fallback(
                prompt, system_instruction, label="text"
            )
            parsed = _parse_json_robust(raw)

            if parsed is None:
                print("[GEMINI] parse failed → retry temp=0", flush=True)
                raw2, tok2, _ = self._call_with_fallback(
                    f"Return ONLY a JSON object.\n\n{prompt[:3000]}",
                    system_instruction,
                    temperature=0.0, max_tokens=4096,
                    label="retry",
                )
                tok   += tok2
                raw    = raw2
                parsed = _parse_json_robust(raw2)

            return LLMResponse(
                raw_text=raw, parsed_json=parsed,
                model_used=model,
                latency_ms=(time.time() - t0) * 1000,
                tokens_used=tok,
                success=parsed is not None,
                error="" if parsed else f"JSON parse failed: {raw[:150]}",
            )
        except Exception as e:
            print(f"[GEMINI] text call failed: {e}", flush=True)
            return LLMResponse(
                raw_text="", success=False,
                error=f"Gemini error: {e}",
                model_used=self._model_name,
                latency_ms=(time.time() - t0) * 1000,
            )

    def _vision_call(self, prompt: str, image_b64: str,
                     system_instruction: str = "") -> LLMResponse:
        t0 = time.time()
        try:
            # Build vision request with inline image
            model = self._working_model or self._model_name
            url   = (f"https://generativelanguage.googleapis.com/v1/models/"
                     f"{model}:generateContent?key={self.api_key}")

            body: dict = {
                "contents": [{
                    "parts": [
                        {"text": prompt},
                        {"inlineData": {
                            "mimeType": "image/png",
                            "data": image_b64,
                        }},
                    ]
                }],
                "generationConfig": {
                    "temperature":      0.1,
                    "maxOutputTokens":  8192,
                    "responseMimeType": "application/json",
                },
            }
            if system_instruction:
                body["systemInstruction"] = {
                    "parts": [{"text": system_instruction}]
                }

            data = json.dumps(body).encode('utf-8')
            req  = urllib.request.Request(
                url, data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                result = json.loads(resp.read())
                raw    = result["candidates"][0]["content"]["parts"][0]["text"]
                usage  = result.get("usageMetadata", {})
                inp    = usage.get("promptTokenCount", 0)
                out    = usage.get("candidatesTokenCount", 0)
                tok    = _log_tokens(f"vision:{model}", inp, out)

            parsed = _parse_json_robust(raw)

            if parsed is None:
                print("[GEMINI] vision parse failed → text retry", flush=True)
                raw2, tok2, _ = self._call_with_fallback(
                    f"Return ONLY a JSON object.\n\n{prompt[:3000]}",
                    system_instruction,
                    temperature=0.0, max_tokens=4096,
                    label="vision-retry",
                )
                tok   += tok2
                parsed = _parse_json_robust(raw2)
                raw    = raw2

            return LLMResponse(
                raw_text=raw, parsed_json=parsed,
                model_used=model,
                latency_ms=(time.time() - t0) * 1000,
                tokens_used=tok,
                success=parsed is not None,
                error="" if parsed else f"Vision parse failed: {raw[:150]}",
            )
        except Exception as e:
            print(f"[GEMINI] vision call failed: {e}", flush=True)
            return LLMResponse(
                raw_text="", success=False,
                error=f"Gemini vision error: {e}",
                model_used=self._model_name,
                latency_ms=(time.time() - t0) * 1000,
            )
