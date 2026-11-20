"""
DocAgent — Gemini API Client

Gemini REST API v1beta, pure urllib (no SDK).
- API: https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
- responseMimeType=application/json, plus a `responseSchema` when the caller
  passes one (structured output: every requested key REQUIRED)
- system_instruction as a separate field

EVERY HTTP ATTEMPT IS RECORDED (Run A, A0): model requested, the model version
the API says answered, finish reason, candidate count, response length, prompt
/ output / THINKING tokens, latency, HTTP status, typed error. Records go to
`llm_contract.ATTEMPTS` (the document's diagnostics) and to one redacted log
line. `tokens_used` INCLUDES thinking tokens: on gemini-2.5 they are billed as
output and they count against `maxOutputTokens`, and leaving them out made a
35-second call look like 5,157 tokens.

RETRIES ARE TYPED (A2). Timeouts, 429 rate limits and 5xx are retried with
bounded exponential backoff plus jitter, honouring Retry-After, at most
LLM_MAX_ATTEMPTS attempts inside one LLM_RETRY_BUDGET_S budget. A quota
exhausted for the day, an invalid request, an auth failure and a policy block
are NEVER retried. The model list is walked ONLY on 404 (model not found) —
a 503 no longer silently answers the request with a different model.
"""
import json
import random
import re
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

from config import settings
from connectors.base import LLMResponse
from log_safety import exc_brief

import llm_contract as C


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_json_robust(raw: str) -> Optional[dict]:
    if not raw:
        return None
    text = raw.strip()

    # Strip thinking model tags <think>...</think> or <thought>...</thought>
    text = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE).strip()
    text = re.sub(r'<thought>[\s\S]*?</thought>', '', text, flags=re.IGNORECASE).strip()

    # Strip markdown fences
    m = re.search(r'```(?:json)?\s*([\s\S]*?)```', text)
    if m:
        text = m.group(1).strip()

    # Find first { … last }
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
    print(f"[GEMINI] JSON parse failed ({len(raw or '')} chars; not logged)", flush=True)
    return None


#: finish reasons that mean the answer was withheld by policy
_BLOCKED_FINISH = {"SAFETY", "RECITATION", "BLOCKLIST", "PROHIBITED_CONTENT",
                   "SPII", "IMAGE_SAFETY", "LANGUAGE"}


def _retry_after(err, body: bytes) -> Optional[float]:
    """Seconds the server asked us to wait: the Retry-After header, else the
    `retryDelay` of a google.rpc.RetryInfo detail. None when neither."""
    try:
        h = err.headers.get("Retry-After") if getattr(err, "headers", None) else None
        if h:
            return max(0.0, float(h))
    except (TypeError, ValueError):
        pass
    m = re.search(rb'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"', body or b"")
    return float(m.group(1)) if m else None


def classify_http(code: int, body: bytes) -> str:
    """The typed kind of an HTTP failure. The body is inspected, never
    logged."""
    if code == 429:
        # Gemini answers both a rate limit and an exhausted quota with 429
        # RESOURCE_EXHAUSTED. A quota whose id names a DAY (or a billing
        # limit) will not come back within any retry budget.
        if re.search(rb"PerDay|per day|billing|exceeded your current quota",
                     body or b"", re.IGNORECASE):
            return C.QUOTA
        return C.TRANSIENT
    if code in (500, 502, 503, 504):
        return C.TRANSIENT
    if code in (401, 403):
        return C.AUTH
    if code == 404:
        return C.MODEL_NOT_FOUND
    if code == 400:
        return C.INVALID_REQUEST
    return C.TRANSIENT if code >= 500 else C.INVALID_REQUEST


# ── per-model request settings (overnight M3, docs/MODEL_MIGRATION.md) ───────
#
# gemini-2.5-* keeps today's behaviour exactly: temperature sent,
# thinkingConfig.thinkingBudget when a budget is set. Google's Gemini 3.x
# pages (read 2026-11-20) say temperature/top_p/top_k are deprecated (ignored
# now, an error in later generations) and that thinking_level replaces
# thinking_budget; gemini-3.8-flash rejects "minimal". Those profiles are
# NOT verified against a live call — the owner's model matrix run is that
# check — and every key can be overridden with GEMINI_MODEL_PROFILES, a JSON
# object {model-prefix: {key: value}}.
#
#   temperature    bool      send generationConfig.temperature
#   thinking       "budget"  thinkingConfig.thinkingBudget (2.5)
#                  "level"   thinkingConfig.thinkingLevel (3.x)
#   thinking_level str|None  the level to send ("low", "medium", ...)
#   max_output     int       cap on maxOutputTokens
MODEL_PROFILES = {
    "gemini-2.5": {"temperature": True, "thinking": "budget",
                   "thinking_level": None, "max_output": 65536},
    "gemini-3.5-flash-lite": {"temperature": False, "thinking": "level",
                              "thinking_level": "minimal", "max_output": 65536},
    "gemini-3.6-flash": {"temperature": False, "thinking": "level",
                         "thinking_level": "low", "max_output": 64000},
    "gemini-3.8-flash": {"temperature": False, "thinking": "level",
                         "thinking_level": "low", "max_output": 65536},
    "gemini-3": {"temperature": False, "thinking": "level",
                 "thinking_level": "low", "max_output": 65536},
}


def model_profile(model: str) -> dict:
    """The request settings for `model`: the longest matching prefix of
    MODEL_PROFILES, then GEMINI_MODEL_PROFILES' overrides. An unknown model
    gets the gemini-2.5 profile — today's request shape."""
    import os
    m = (model or "").lower().replace("models/", "")
    table = {k: dict(v) for k, v in MODEL_PROFILES.items()}
    raw = os.environ.get("GEMINI_MODEL_PROFILES") or C.setting("GEMINI_MODEL_PROFILES", "") or ""
    if raw:
        try:
            for k, v in json.loads(raw).items():
                if isinstance(v, dict):
                    table.setdefault(str(k).lower(), {}).update(v)
        except (ValueError, AttributeError):
            print("[GEMINI] GEMINI_MODEL_PROFILES is not a JSON object — ignored", flush=True)
    hit = max((k for k in table if m.startswith(k)), key=len, default=None)
    out = dict(MODEL_PROFILES["gemini-2.5"])
    out.update(table.get(hit, {}))
    return out


def _supports_thinking_config(model: str) -> bool:
    m = (model or "").lower()
    return m.startswith("gemini-2.5") or m.startswith("gemini-3") \
        or m in ("gemini-flash-latest", "gemini-flash-lite-latest")


# ── Client ────────────────────────────────────────────────────────────────────

class GeminiClient:
    """Direct v1beta REST client. The model comes from GEMINI_MODEL.

    Overnight M1: there is no built-in candidate list any more. It used to
    walk gemini-2.5-flash-lite / gemini-2.5-flash / gemini-flash-latest /
    gemini-flash-lite-latest whenever a model answered 404, so a retired or
    mistyped model silently became another model's extraction. Fallbacks are
    only what GEMINI_MODEL_FALLBACKS lists (comma-separated, default empty);
    with none, a 404 fails the call with the model named."""

    BASE_URL    = "https://generativelanguage.googleapis.com/v1beta/models"

    @staticmethod
    def fallbacks() -> list:
        import os
        raw = os.environ.get("GEMINI_MODEL_FALLBACKS")
        if raw is None:
            raw = C.setting("GEMINI_MODEL_FALLBACKS", "") or ""
        return [m.strip().replace("models/", "") for m in str(raw).split(",") if m.strip()]

    def __init__(self, api_key: str = ""):
        self.api_key       = api_key or settings.GEMINI_API_KEY
        preferred          = getattr(settings, 'GEMINI_MODEL', 'gemini-2.5-flash')
        # Strip models/ prefix — we build the URL ourselves
        self._preferred    = preferred.replace('models/', '').strip()
        self._good_model   = None   # cached after first successful call
        print(f"[GEMINI] client ready | preferred={self._preferred}", flush=True)

    # ── REST call ─────────────────────────────────────────────────────────────

    def _post(self, model: str, body: dict, timeout: float) -> Tuple[str, dict]:
        """One HTTP attempt. Returns (text, info) or raises LLMCallError.

        `info` holds what the API said about the answer: finish_reason,
        candidate_count, model_version, prompt/output/thinking tokens (None
        when not reported), block_reason. An answer the model withheld or
        truncated is RETURNED with its finish reason, not raised — the caller
        types it, because a truncated answer is not a transport failure."""
        url  = f"{self.BASE_URL}/{model}:generateContent?key={self.api_key}"
        data = json.dumps(body).encode('utf-8')
        req  = urllib.request.Request(
            url, data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as e:
            raw = b""
            try:
                raw = e.read()
            except Exception:
                pass
            kind = classify_http(e.code, raw)
            raise C.LLMCallError(kind, f"HTTP {e.code} {e.reason}", status=e.code,
                                 retry_after=_retry_after(e, raw)) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            raise C.LLMCallError(C.TRANSIENT, f"{type(e).__name__}") from None
        except json.JSONDecodeError:
            raise C.LLMCallError(C.TRANSIENT, "non-JSON HTTP body") from None

        usage = result.get("usageMetadata") or {}
        candidates = result.get("candidates") or []
        info = {
            "http_status": status,
            "model_version": result.get("modelVersion"),
            "candidate_count": len(candidates),
            "prompt_tokens": usage.get("promptTokenCount"),
            "output_tokens": usage.get("candidatesTokenCount"),
            "thinking_tokens": usage.get("thoughtsTokenCount"),
            "finish_reason": None,
            "block_reason": (result.get("promptFeedback") or {}).get("blockReason"),
        }
        if not candidates:
            return "", info
        cand = candidates[0] or {}
        info["finish_reason"] = cand.get("finishReason")
        parts = ((cand.get("content") or {}).get("parts")) or []
        text = "".join(p.get("text", "") for p in parts
                       if isinstance(p, dict) and not p.get("thought"))
        return text, info

    def _gen_config(self, model, temperature, max_tokens, response_schema,
                    thinking_budget, force_json=True) -> dict:
        prof = model_profile(model)
        cap = int(prof.get("max_output") or max_tokens)
        gen = {"maxOutputTokens": min(int(max_tokens), cap)}
        if prof.get("temperature", True):
            gen = {"temperature": temperature, **gen}
        if force_json:
            gen["responseMimeType"] = "application/json"
        if response_schema:
            gen["responseSchema"] = response_schema
        if prof.get("thinking") == "level":
            if prof.get("thinking_level"):
                gen["thinkingConfig"] = {"thinkingLevel": str(prof["thinking_level"])}
        elif thinking_budget is not None and _supports_thinking_config(model):
            gen["thinkingConfig"] = {"thinkingBudget": int(thinking_budget)}
        return gen

    def _generate(self, parts: list, system_instruction: str = "",
                  temperature: float = 0.1, max_tokens: Optional[int] = None,
                  model: Optional[str] = None, response_schema: Optional[dict] = None,
                  thinking_budget=None, force_json: bool = True,
                  label: str = "extract") -> Tuple[str, dict]:
        """Call Gemini with typed retries. Returns (text, meta); raises
        LLMCallError (carrying `.attempts`) when no answer could be had.

        meta: model_used, model_version, finish_reason, block_reason,
        candidate_count, tokens (incl. thinking), attempts, structured."""
        max_tokens = int(max_tokens or C.setting("GEMINI_MAX_OUTPUT_TOKENS", 8192))
        if thinking_budget is None:
            thinking_budget = C.setting("GEMINI_THINKING_BUDGET", None)
        max_attempts = max(1, int(C.setting("LLM_MAX_ATTEMPTS", 3)))
        budget = float(C.setting("LLM_RETRY_BUDGET_S", 180.0))
        base = float(C.setting("LLM_BACKOFF_BASE_S", 1.0))
        timeout = float(C.setting("LLM_CALL_TIMEOUT_S", 120.0))
        n_images = sum(1 for p in parts if isinstance(p, dict) and "inlineData" in p)

        ordered = []
        for m in ([model or self._preferred] + self.fallbacks()):
            if m and m not in ordered:
                ordered.append(m)

        attempts: list = []
        deadline = time.monotonic() + budget
        schema = response_schema
        last: Optional[C.LLMCallError] = None
        for m in ordered:
            tries, reason = 0, ""
            while True:
                body = {"contents": [{"parts": parts}],
                        "generationConfig": self._gen_config(
                            m, temperature, max_tokens, schema, thinking_budget,
                            force_json)}
                if system_instruction:
                    body["systemInstruction"] = {"parts": [{"text": system_instruction}]}
                rec = C.new_attempt(m, retry=len(attempts), reason=reason,
                                    images=n_images)
                rec["structured_output"] = bool(schema)
                rec["temperature"] = temperature
                t0 = time.monotonic()
                try:
                    text, info = self._post(m, body, timeout)
                except C.LLMCallError as e:
                    rec["latency_ms"] = round((time.monotonic() - t0) * 1000)
                    rec["http_status"] = e.status
                    rec["error_kind"] = e.kind
                    rec["parse"] = "not_attempted"
                    attempts.append(C.finish_attempt(rec))
                    last = e
                    if e.kind == C.MODEL_NOT_FOUND:
                        break                       # discovery: next model
                    if e.kind == C.INVALID_REQUEST and schema:
                        # Our OWN schema may be what the API refused (too
                        # many properties for the model). Asked once more
                        # without it; the answer is validated either way.
                        schema, reason = None, "schema_rejected"
                        continue
                    left = deadline - time.monotonic()
                    if e.kind in C.RETRYABLE_TRANSPORT and tries + 1 < max_attempts \
                            and left > 0:
                        delay = base * (2 ** tries) + random.uniform(0, base)
                        if e.retry_after is not None:
                            delay = max(delay, e.retry_after)
                        if delay > left:
                            e.attempts = attempts
                            raise e
                        time.sleep(delay)
                        tries += 1
                        reason = f"{e.kind}:{e.status or ''}".rstrip(":")
                        continue
                    e.attempts = attempts
                    raise e
                rec["latency_ms"] = round((time.monotonic() - t0) * 1000)
                for k in ("http_status", "model_version", "candidate_count",
                          "prompt_tokens", "output_tokens", "thinking_tokens",
                          "finish_reason"):
                    rec[k] = info.get(k)
                rec["response_chars"] = len(text or "")
                attempts.append(C.finish_attempt(rec, log=False))
                self._good_model = m
                tok = C.total_tokens(info.get("prompt_tokens"),
                                     info.get("output_tokens"),
                                     info.get("thinking_tokens"))
                return text, {
                    "model_used": m,
                    "model_version": info.get("model_version"),
                    "finish_reason": info.get("finish_reason"),
                    "block_reason": info.get("block_reason"),
                    "candidate_count": info.get("candidate_count"),
                    "tokens": tok,
                    "attempts": attempts,
                    "structured": bool(schema),
                }
        err = last or C.LLMCallError(C.MODEL_NOT_FOUND, "no model answered")
        if err.kind == C.MODEL_NOT_FOUND:
            # M1: say WHICH model, and that nothing was substituted
            tried = ", ".join(ordered)
            err = C.LLMCallError(
                C.MODEL_NOT_FOUND,
                f"model not found (HTTP 404): {tried} — no other model was used"
                + ("" if len(ordered) > 1 else
                   "; set GEMINI_MODEL to an available model or list fallbacks in "
                   "GEMINI_MODEL_FALLBACKS"),
                status=getattr(err, "status", 404))
        err.attempts = attempts
        raise err

    # Kept for classification and older callers: (raw_text, total_tokens, model).
    def _call(self, prompt: str, system_instruction: str = "",
              temperature: float = 0.1, max_tokens: int = 8192,
              label: str = "text", model: str = None) -> Tuple[str, int, str]:
        try:
            text, meta = self._generate([{"text": prompt}], system_instruction,
                                        temperature, max_tokens, model, label=label)
        except C.LLMCallError as e:
            raise RuntimeError(f"All Gemini models failed. Last error: {e}") from None
        C.log_attempt(meta["attempts"][-1])
        return text, meta["tokens"] or 0, meta["model_used"]

    @staticmethod
    def _image_parts(image_b64) -> list:
        imgs = image_b64 if isinstance(image_b64, (list, tuple)) else [image_b64]
        return [{"inlineData": {"mimeType": "image/jpeg", "data": im}}
                for im in imgs if im]

    def _call_vision(self, prompt: str, image_b64,
                     system_instruction: str = "", model: str = None,
                     temperature: float = 0.1) -> Tuple[str, int, str]:
        """Vision call — text prompt + one or more page images."""
        try:
            text, meta = self._generate([{"text": prompt}] + self._image_parts(image_b64),
                                        system_instruction, temperature, None, model,
                                        label="vision")
        except C.LLMCallError as e:
            raise RuntimeError(f"All vision models failed: {e}") from None
        C.log_attempt(meta["attempts"][-1])
        return text, meta["tokens"] or 0, meta["model_used"]

    # ── Response builder ──────────────────────────────────────────────────────

    def _make_response(self, raw: str, tok: int, model: str,
                       t0: float, label: str) -> LLMResponse:
        """Classification only: one re-ask when the JSON does not parse."""
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

    def _extraction_response(self, parts, system_instruction, model, temperature,
                             t0, response_schema=None, max_output_tokens=None,
                             thinking_budget=None) -> LLMResponse:
        """One extraction: typed, instrumented, never re-asked behind the
        caller's back. A JSON parse failure used to trigger a second call
        that sent the model the first 1,000 characters of its own broken
        answer, with no document — and whatever came back was a SUCCESS. A
        truncated answer turned into a shorter one that looked complete."""
        try:
            text, meta = self._generate(parts, system_instruction, temperature,
                                        max_output_tokens, model,
                                        response_schema=response_schema,
                                        thinking_budget=thinking_budget)
        except C.LLMCallError as e:
            attempts = list(getattr(e, "attempts", []) or [])
            return LLMResponse(raw_text="", success=False,
                               error=f"Gemini error: {e}", error_kind=e.kind,
                               model_used=model or self._preferred,
                               latency_ms=(time.time() - t0) * 1000,
                               tokens_used=sum(a.get("total_tokens") or 0
                                               for a in attempts),
                               attempts=attempts)
        attempts = meta["attempts"]
        rec = attempts[-1]
        finish = meta["finish_reason"]
        kind, parsed = None, None
        if meta["block_reason"] or finish in _BLOCKED_FINISH:
            kind = C.BLOCKED
        elif meta["candidate_count"] == 0:
            kind = C.NO_CANDIDATE
        elif finish == "MAX_TOKENS":
            # A truncated answer is never parsed into cells, even when the
            # cut happens to leave balanced braces.
            kind = C.MAX_TOKENS
        elif not (text or "").strip():
            kind = C.EMPTY
        else:
            parsed = _parse_json_robust(text)
            if parsed is None:
                kind = C.INVALID_JSON
            elif not parsed:
                kind = C.EMPTY
        rec["parse"] = ("ok" if kind is None else
                        "invalid_json" if kind == C.INVALID_JSON else
                        "empty" if kind == C.EMPTY else "not_attempted")
        if kind:
            rec["error_kind"] = kind
        C.log_attempt(rec)
        return LLMResponse(
            raw_text=text, parsed_json=parsed if kind is None else None,
            model_used=meta["model_used"],
            latency_ms=(time.time() - t0) * 1000,
            tokens_used=sum(a.get("total_tokens") or 0 for a in attempts),
            success=kind is None,
            error="" if kind is None else f"{kind} (finish={finish})",
            error_kind=kind, finish_reason=finish,
            model_version=meta["model_version"], attempts=attempts)

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
                     system_instruction: str = "", model: str = None,
                     temperature: float = 0.1, **options) -> LLMResponse:
        t0 = time.time()
        # Fold the document text into the prompt.
        # Without this, callers that pass the document via `text=` (e.g. the
        # no-template orchestrator path) send only instructions and no content,
        # and Gemini returns "No document content was provided".
        user_prompt = (
            f"{prompt}\n\nDocument content:\n\n{text}" if text else prompt
        )
        return self._extraction_response([{"text": user_prompt}], system_instruction,
                                         model, temperature, t0, **options)

    def extract_data_vision(self, image_b64: str, prompt: str,
                             system_instruction: str = "", model: str = None,
                             temperature: float = 0.1, **options) -> LLMResponse:
        t0 = time.time()
        return self._extraction_response(
            [{"text": prompt}] + self._image_parts(image_b64), system_instruction,
            model, temperature, t0, **options)
