"""
Record/replay cache for LLM calls, installed at the single provider-agnostic
chokepoint: ``LLMRouter.extract`` / ``LLMRouter.classify`` (every extraction
call, Gemini or Groq, template understanding included, returns through them).

Modes:
  record — serve from cache when present, else call the live provider and
           persist the response to tests/llm_cache/<key>.json.
  replay — never touch the network. A cache miss raises CacheMiss: either the
           document was never recorded, or a code change altered the prompt
           (re-record in that case).
  live   — always call the provider; never read the cache, never write it.
           This is what --repeat stability runs use: reading the cache would
           return the identical answer every time and report every field as
           stable regardless of how much the model actually varies.

The key is a sha256 over the full request: method, text, prompt,
system_instruction, model override, and a hash of each page image. Prompts
embed the document text/binding map, so the key changes whenever the code
changes what it asks the model — replay can never silently serve a response
for a different question.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Optional

from tests.harness.bootstrap import CACHE_DIR, bootstrap


class CacheMiss(RuntimeError):
    pass


class ReplayEnvironmentError(RuntimeError):
    """This machine cannot reproduce the requests the cache was recorded with."""


#: THE KEY INCLUDES EVERY PAGE IMAGE (`_img_sig`), and a page image is what
#: pdf2image + Poppler (`pdftoppm`) + Pillow's JPEG encoder made of the PDF on
#: the machine that recorded it. A machine with no `pdftoppm` on PATH renders
#: NO images — the request differs, every lookup misses, and the harness used
#: to report 0.0% as though the engine had failed (Codex, round 7: 0 hits / 30
#: misses). A different Poppler or Pillow renders different bytes and misses
#: the same way. Replay therefore checks first, and says which it is.
FINGERPRINT_FILE = "_render_fingerprint.json"
FINGERPRINT_PDF = "CHQ-001847.pdf"


def render_fingerprint() -> Optional[str]:
    """`_img_sig` of the pipeline's own page-1 image of FINGERPRINT_PDF, or
    None when nothing renders (no Poppler)."""
    bootstrap()
    from tests.harness.bootstrap import PDF_DIR
    from core.preprocessor import ProcessedDocument, _pdf_pages_to_images
    doc = ProcessedDocument(source_path="", filename=FINGERPRINT_PDF,
                            file_type="pdf", total_pages=1)
    _pdf_pages_to_images(PDF_DIR / FINGERPRINT_PDF, doc)
    return _img_sig(doc.page_images_b64[0])[0] if doc.page_images_b64 else None


def check_replay_environment(cache_dir) -> None:
    """Raise ReplayEnvironmentError when replay cannot reproduce the recorded
    requests on this machine; return quietly when it can."""
    import shutil
    pinned_path = Path(cache_dir) / FINGERPRINT_FILE
    pinned = (json.loads(pinned_path.read_text(encoding="utf-8"))
              if pinned_path.exists() else None)
    got = render_fingerprint()
    if got is None:
        raise ReplayEnvironmentError(
            "replay needs page images and none render here: pdftoppm (Poppler) "
            f"is not on PATH (shutil.which -> {shutil.which('pdftoppm')!r}). "
            "Every cache key includes the page images, so every lookup would "
            "miss. Put Poppler's bin directory on PATH and re-run.")
    if pinned and got != pinned.get("page_image_sig"):
        raise ReplayEnvironmentError(
            f"this machine renders {FINGERPRINT_PDF} page 1 as {got}, the cache "
            f"was recorded with {pinned.get('page_image_sig')} "
            f"({pinned.get('recorded_with')}). A different Poppler or Pillow "
            "makes different page images, so every key would miss.")


def _img_sig(image_b64: Any) -> list:
    if not image_b64:
        return []
    imgs = image_b64 if isinstance(image_b64, (list, tuple)) else [image_b64]
    return [hashlib.sha256(str(i).encode("utf-8")).hexdigest()[:16] for i in imgs]


#: The router's default sampling temperature. A call at this temperature keys
#: exactly as it did before temperature was threaded through, so the committed
#: cache stays valid; a call at any other temperature is a genuinely different
#: request and gets its own key rather than silently colliding.
DEFAULT_TEMPERATURE = 0.1


def request_key(method: str, *, text: str = "", image_b64: Any = "",
                prompt: str = "", system_instruction: str = "",
                model: Optional[str] = None,
                temperature: float = DEFAULT_TEMPERATURE) -> str:
    payload = {
        "method": method,
        "text": text or "",
        "prompt": prompt or "",
        "system_instruction": system_instruction or "",
        "model": model or "",
        "images": _img_sig(image_b64),
    }
    if temperature != DEFAULT_TEMPERATURE:
        payload["temperature"] = temperature
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


class LLMCache:
    def __init__(self, mode: str = "replay", cache_dir=None):
        assert mode in ("record", "replay", "live"), mode
        self.mode = mode
        self.dir = cache_dir or CACHE_DIR
        self.context = ""  # e.g. current document id, stored in meta
        self.stats = {"hits": 0, "recorded": 0, "live": 0, "misses": 0}
        self.calls = []  # (method, key, source) in call order
        self._orig = {}

    # ── persistence ──────────────────────────────────────────────────────────

    def _path(self, key: str):
        return self.dir / f"{key[:32]}.json"

    def _load(self, key: str):
        p = self._path(key)
        if not p.exists():
            return None
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("key") != key:  # 32-hex-prefix collision guard
            return None
        return data

    def _save(self, key: str, method: str, prompt: str, model, resp) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        record = {
            "key": key,
            "meta": {
                "method": method,
                "context": self.context,
                "model_requested": model or "",
                "model_used": getattr(resp, "model_used", ""),
                "tokens_used": getattr(resp, "tokens_used", 0),
                "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "prompt_preview": (prompt or "")[:300],
            },
            "response": {
                "raw_text": getattr(resp, "raw_text", ""),
                "parsed_json": getattr(resp, "parsed_json", None),
                "model_used": getattr(resp, "model_used", ""),
                "tokens_used": getattr(resp, "tokens_used", 0),
                "success": getattr(resp, "success", False),
                "error": getattr(resp, "error", ""),
            },
        }
        self._path(key).write_text(
            json.dumps(record, indent=1, ensure_ascii=False, default=str),
            encoding="utf-8")

    def _to_response(self, data: dict):
        from connectors.groq_client import LLMResponse
        r = data["response"]
        return LLMResponse(raw_text=r.get("raw_text", ""),
                          parsed_json=r.get("parsed_json"),
                          model_used=r.get("model_used", ""),
                          tokens_used=int(r.get("tokens_used") or 0),
                          latency_ms=0,
                          success=bool(r.get("success")),
                          error=r.get("error", ""))

    # ── the wrapped calls ────────────────────────────────────────────────────

    def _dispatch(self, method: str, orig, router, kwargs: dict):
        key = request_key(method, text=kwargs.get("text", ""),
                          image_b64=kwargs.get("image_b64", ""),
                          prompt=kwargs.get("prompt", ""),
                          system_instruction=kwargs.get("system_instruction", ""),
                          model=kwargs.get("model"),
                          temperature=kwargs.get("temperature",
                                                 DEFAULT_TEMPERATURE))
        # 'live' deliberately does NOT consult the cache. Stability runs exist
        # to observe the model's nondeterminism; serving them a cached answer
        # would report every field as stable no matter how much it varies.
        if self.mode != "live":
            cached = self._load(key)
            if cached is not None:
                self.stats["hits"] += 1
                self.calls.append((method, key, "cache"))
                return self._to_response(cached)

        if self.mode == "replay":
            self.stats["misses"] += 1
            raise CacheMiss(
                f"LLM cache miss in replay mode for {method} "
                f"(context={self.context!r}, key={key[:16]}…). Either this "
                f"document was never recorded, or a code change altered the "
                f"prompt. Re-record with: python -m tests.harness.runner "
                f"--mode record")

        resp = orig(router, **kwargs)
        if self.mode == "record" and getattr(resp, "success", False):
            self._save(key, method, kwargs.get("prompt", ""),
                       kwargs.get("model"), resp)
            self.stats["recorded"] += 1
            self.calls.append((method, key, "recorded"))
        else:
            self.stats["live"] += 1
            self.calls.append((method, key, "live"))
        return resp

    # ── install / uninstall ──────────────────────────────────────────────────

    def install(self) -> None:
        bootstrap()
        from connectors.llm_router import LLMRouter

        if self.mode == "replay" and not self._orig:
            check_replay_environment(self.dir)

        if self._orig:
            return
        self._orig["extract"] = LLMRouter.extract
        self._orig["classify"] = LLMRouter.classify
        cache = self

        def extract(router, text: str = "", image_b64="", prompt: str = "",
                    system_instruction: str = "", model: str = None,
                    temperature: float = DEFAULT_TEMPERATURE):
            return cache._dispatch("extract", cache._orig["extract"], router, {
                "text": text, "image_b64": image_b64, "prompt": prompt,
                "system_instruction": system_instruction, "model": model,
                "temperature": temperature})

        def classify(router, text: str = "", image_b64: str = "",
                     prompt: str = ""):
            return cache._dispatch("classify", cache._orig["classify"], router, {
                "text": text, "image_b64": image_b64, "prompt": prompt})

        LLMRouter.extract = extract
        LLMRouter.classify = classify

    def uninstall(self) -> None:
        if not self._orig:
            return
        from connectors.llm_router import LLMRouter
        LLMRouter.extract = self._orig.pop("extract")
        LLMRouter.classify = self._orig.pop("classify")

    def __enter__(self):
        self.install()
        return self

    def __exit__(self, *exc):
        self.uninstall()
