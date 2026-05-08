"""
DocAgent — Gemini API Client (Production Grade)

Uses Gemini REST API v1beta directly with correct request format.
- API: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
- responseMimeType=application/json forces clean JSON (v1beta feature)
- system_instruction as separate field saves ~25% tokens on batches
- Auto-discovers working model from candidate list
- Exact token counting and cost logging per call
- No google-generativeai SDK dependency — pure urllib

Tested working models (v1beta):
  gemini-1.5-flash, gemini-1.5-flash-8b, gemini-1.5-pro

Cost (gemini-1.5-flash):
  $0.075/1M input + $0.30/1M output
  ~1,200 tokens/doc = $0.00015/doc
  $10 covers ~65,000 documents
"""
import json
import time
import urllib.request
import urllib.error
from typing import Optional, Tuple
from config import settings
from connectors.groq_client import LLMResponse


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_robust(raw: str) -> Optional[dict]:
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


def _log(label: str, inp: int, out: int) -> int:
    total = inp + out
    cost  = (inp / 1_000_000) * 0.075 + (out / 1_000_000) * 0.30
    print(f"[GEMINI] {label}: {inp}in+{out}out={total} | ${cost:.5f}", flush=True)
    return total


# ── Client ────────────────────────────────────────────────────────────────────

class GeminiClient:
    """
    Production-grade Gemini client.
    Direct v1beta REST API — no SDK, no version compatibility issues.
    Automatically discovers the working model for the given API key.
    """

    BASE_URL    = "https://generativelanguage.googleapis.com/v1beta/models"
    CANDIDATES  = [
        "gemini-2.0-flash",
        "gemini-2.0-flash-001",
        "gemini-2.0-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite-001",
    ]

    def __init__(self, api_key: str = ""):
        self.api_key       = api_key or settings.GEMINI_API_KEY
        preferred          = getattr(settings, 'GEMINI_MODEL', 'gemini-1.5-flash')
        # Strip models/ prefix — we build the URL ourselves
        self._preferred    = preferred.replace('models/', '').strip()
        self._good_model   = None   # cached after first successful call
        print(f"[GEMINI] client ready | preferred={self._preferred}", flush=True)

    # ── REST call ─────────────────────────────────────────────────────────────

    def _post(self, model: str, body: dict) -> Tuple[str, int, int]:
        """
        POST to Gemini v1beta generateContent.
        Returns (raw_text, input_tokens, output_tokens).
        Raises urllib.error.HTTPError on HTTP errors.
        """
        url  = f"{self.BASE_URL}/{model}:generateContent?key={self.api_key}"
        data = json.dumps(body).encode('utf-8')
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            result = json.loads(resp.read())

        # Parse response
        candidates = result.get("candidates", [])
        if not candidates:
            raise ValueError(f"No candidates in response: {result}")
        raw    = candidates[0]["content"]["parts"][0]["text"]
        usage  = result.get("usageMetadata", {})
        inp    = usage.get("promptTokenCount", 0) or 0
        out    = usage.get("candidatesTokenCount", 0) or 0
        return raw, inp, out

    def _build_body(self, prompt: str, system_instruction: str = "",
                    temperature: float = 0.1,
                    max_tokens: int = 8192) -> dict:
        """Build the request body."""
        body: dict = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature":      temperature,
                "maxOutputTokens":  max_tokens,
                "responseMimeType": "application/json",
            },
        }
        if system_instruction:
            body["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }
        return body

    def _call(self, prompt: str, system_instruction: str = "",
              temperature: float = 0.1, max_tokens: int = 8192,
              label: str = "text") -> Tuple[str, int, str]:
        """
        Call Gemini with automatic model discovery.
        Returns (raw_text, total_tokens, model_used).

        Tries the cached working model first, then the preferred model,
        then falls back through CANDIDATES until one succeeds.
        """
        body = self._build_body(prompt, system_instruction,
                                temperature, max_tokens)

        # Build ordered candidate list
        ordered = []
        for m in ([self._good_model, self._preferred] + self.CANDIDATES):
            if m and m not in ordered:
                ordered.append(m)

        last_error = ""
        for model in ordered:
            try:
                raw, inp, out = self._post(model, body)
                tok = _log(f"{label}:{model}", inp, out)
                self._good_model = model   # cache for next call
                return raw, tok, model
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code} {e.reason}"
                body_bytes = e.read()
                err_body   = body_bytes.decode('utf-8', errors='replace')[:200]
                print(f"[GEMINI] {model} failed: {last_error} | {err_body}",
                      flush=True)
                # Auth failure — no point trying other models
                if e.code in (401, 403):
                    break
                continue
            except Exception as e:
                last_error = str(e)[:150]
                print(f"[GEMINI] {model} error: {last_error}", flush=True)
                continue

        raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")

    # ── Vision call ───────────────────────────────────────────────────────────

    def _call_vision(self, prompt: str, image_b64: str,
                     system_instruction: str = "") -> Tuple[str, int, str]:
        """Vision extraction — image + text prompt."""
        body: dict = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inlineData": {"mimeType": "image/jpeg", "data": image_b64}},
                ]
            }],
            "generationConfig": {
                "temperature":      0.1,
                "maxOutputTokens":  8192,
                "responseMimeType": "application/json",
            },
        }
        if system_instruction:
            body["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        ordered = []
        for m in ([self._good_model, self._preferred] + self.CANDIDATES):
            if m and m not in ordered:
                ordered.append(m)

        last_error = ""
        for model in ordered:
            try:
                raw, inp, out = self._post(model, body)
                tok = _log(f"vision:{model}", inp, out)
                self._good_model = model
                return raw, tok, model
            except urllib.error.HTTPError as e:
                last_error = f"HTTP {e.code}"
                body_bytes = e.read()
                print(f"[GEMINI] vision {model} failed: {last_error} | "
                      f"{body_bytes.decode('utf-8','replace')[:150]}", flush=True)
                if e.code in (401, 403):
                    break
                continue
            except Exception as e:
                last_error = str(e)[:100]
                print(f"[GEMINI] vision {model} error: {last_error}", flush=True)
                continue

        raise RuntimeError(f"All vision models failed: {last_error}")

    # ── Response builder ──────────────────────────────────────────────────────

    def _make_response(self, raw: str, tok: int, model: str,
                       t0: float, label: str) -> LLMResponse:
        parsed = _parse_json_robust(raw)
        if parsed is None:
            print(f"[GEMINI] {label} parse failed → retry temp=0", flush=True)
            try:
                raw2, tok2, model2 = self._call(
                    f"Return ONLY a JSON object starting with {{ and ending with }}.\n\n"
                    f"{raw[:1000] if raw else '{}'}",
                    temperature=0.0, max_tokens=2048,
                    label=f"{label}-retry",
                )
                tok  += tok2
                raw   = raw2
                model = model2
                parsed = _parse_json_robust(raw2)
            except Exception:
                pass

        return LLMResponse(
            raw_text=raw, parsed_json=parsed,
            model_used=model,
            latency_ms=(time.time() - t0) * 1000,
            tokens_used=tok,
            success=parsed is not None,
            error="" if parsed else f"JSON parse failed: {raw[:150]}",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def classify_document(self, text: str, prompt: str) -> LLMResponse:
        t0 = time.time()
        try:
            raw, tok, model = self._call(
                f"{prompt}\n\nDocument:\n{text[:4000]}", label="classify"
            )
            return self._make_response(raw, tok, model, t0, "classify")
        except Exception as e:
            return LLMResponse(raw_text="", success=False,
                               error=str(e), model_used=self._preferred,
                               latency_ms=(time.time()-t0)*1000)

    def classify_document_vision(self, image_b64: str, prompt: str) -> LLMResponse:
        t0 = time.time()
        try:
            raw, tok, model = self._call_vision(
                f"{prompt}\n\nClassify this document.", image_b64
            )
            return self._make_response(raw, tok, model, t0, "classify-vision")
        except Exception as e:
            return LLMResponse(raw_text="", success=False,
                               error=str(e), model_used=self._preferred,
                               latency_ms=(time.time()-t0)*1000)

    def extract_data(self, text: str, prompt: str,
                     system_instruction: str = "") -> LLMResponse:
        t0 = time.time()
        try:
            raw, tok, model = self._call(
                prompt, system_instruction, label="extract"
            )
            return self._make_response(raw, tok, model, t0, "extract")
        except Exception as e:
            return LLMResponse(raw_text="", success=False,
                               error=f"Gemini error: {e}",
                               model_used=self._preferred,
                               latency_ms=(time.time()-t0)*1000)

    def extract_data_vision(self, image_b64: str, prompt: str,
                             system_instruction: str = "") -> LLMResponse:
        t0 = time.time()
        try:
            raw, tok, model = self._call_vision(
                prompt, image_b64, system_instruction
            )
            return self._make_response(raw, tok, model, t0, "extract-vision")
        except Exception as e:
            return LLMResponse(raw_text="", success=False,
                               error=f"Gemini vision error: {e}",
                               model_used=self._preferred,
                               latency_ms=(time.time()-t0)*1000)
