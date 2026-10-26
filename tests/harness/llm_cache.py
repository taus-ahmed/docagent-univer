"""
Record/replay cache for LLM calls, installed at the single provider-agnostic
chokepoint: ``LLMRouter.extract`` / ``LLMRouter.classify`` (every extraction
call, whichever provider, template understanding included, returns through them).

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

import base64
import hashlib
import io
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from tests.harness.bootstrap import CACHE_DIR, bootstrap


class ReplayAbort(BaseException):
    """Replay could not answer a request.

    A BaseException ON PURPOSE. The engine wraps every model call in
    `except Exception` and turns a failure into a failed call, which a test or
    the harness then scores as a wrong answer — a miss would pass for an
    engine defect, or for nothing at all. Deriving from BaseException lets it
    through those handlers to the test, the hook in tests/conftest.py, or the
    runner."""


class CacheMiss(ReplayAbort):
    pass


class ReplayEnvironmentError(ReplayAbort):
    """This machine cannot reproduce the requests the cache was recorded with."""


#: THE KEY INCLUDES EVERY PAGE IMAGE (`_img_sig`), and a page image is what
#: pdf2image + Poppler (`pdftoppm`) + Pillow's JPEG encoder made of the PDF on
#: the machine that recorded it. A machine with no `pdftoppm` on PATH renders
#: NO images — the request differs, every lookup misses, and the harness used
#: to report 0.0% as though the engine had failed (0 hits / 30 misses, seen in
#: review). A different Poppler or Pillow renders different bytes and misses
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


def _pinned_signature(cache_dir) -> str:
    """The recorded page-image signature, or ReplayEnvironmentError. FAILS
    CLOSED: a missing, empty, unparseable or incomplete file is no evidence
    the cache can be reproduced, so it is never read as "nothing to check"."""
    path = Path(cache_dir) / FINGERPRINT_FILE
    try:
        pinned = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ReplayEnvironmentError(
            f"replay cannot check this machine: {path} is missing or not "
            f"readable JSON ({type(exc).__name__}: {exc}). It pins how the "
            "cache's page images were rendered; restore it from git.") from exc
    sig = pinned.get("page_image_sig") if isinstance(pinned, dict) else None
    if not isinstance(sig, str) or not sig:
        raise ReplayEnvironmentError(
            f"replay cannot check this machine: {path} carries no "
            "page_image_sig. Restore it from git.")
    return sig


#: cache directories whose preflight passed in this process.
_PREFLIGHT_PASSED: set = set()


def ensure_replay_environment(cache_dir) -> None:
    """check_replay_environment once per process per cache directory. A
    failure is never remembered: it raises again on every entry."""
    key = str(Path(cache_dir).resolve())
    if key not in _PREFLIGHT_PASSED:
        check_replay_environment(cache_dir)
        _PREFLIGHT_PASSED.add(key)


def check_replay_environment(cache_dir) -> None:
    """Raise ReplayEnvironmentError when replay cannot reproduce the recorded
    requests on this machine; return quietly only when it can."""
    import shutil
    pinned = _pinned_signature(cache_dir)
    got = render_fingerprint()
    if got is None:
        raise ReplayEnvironmentError(
            "replay needs page images and none render here: pdftoppm (Poppler) "
            f"is not on PATH (shutil.which -> {shutil.which('pdftoppm')!r}). "
            "Every cache key includes the page images, so every lookup would "
            "miss. Put Poppler's bin directory on PATH and re-run.")
    if got != pinned:
        raise ReplayEnvironmentError(
            f"this machine renders {FINGERPRINT_PDF} page 1 as {got}, the cache "
            f"was recorded with {pinned} (see {FINGERPRINT_FILE}). A different "
            "Poppler or Pillow makes different page images, so every key would "
            "miss.")


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


# ── the image-independent alias (docs/proposals/replay-portability.md) ──────
#
# A native-text document's request does not depend on the render for anything
# but the page images themselves: the text and the prompt come from the PDF's
# own text layer. Its alias is the request with each image's BYTES replaced by
# its width and height, so a machine whose Poppler or Pillow encodes the same
# page differently still finds the answer. A document with an OCR'd page gets
# no alias — its text came from the render — and keeps the exact key and the
# render preflight. The index is built on the recording machine, where every
# exact key still matches (`python -m tests.harness.alias_index`).

ALIAS_INDEX_FILE = "_alias_index.json"


def _img_shapes(image_b64: Any) -> list:
    """[width, height] of each page image, read from its header."""
    if not image_b64:
        return []
    from PIL import Image
    imgs = image_b64 if isinstance(image_b64, (list, tuple)) else [image_b64]
    out = []
    for i in imgs:
        try:
            with Image.open(io.BytesIO(base64.b64decode(str(i)))) as im:
                out.append(list(im.size))
        except Exception:
            out.append(None)      # unreadable: still counted, never matched loosely
    return out


def alias_key(method: str, *, text: str = "", image_b64: Any = "",
              prompt: str = "", system_instruction: str = "",
              model: Optional[str] = None,
              temperature: float = DEFAULT_TEMPERATURE) -> str:
    payload = {
        "alias": 1,
        "method": method,
        "text": text or "",
        "prompt": prompt or "",
        "system_instruction": system_instruction or "",
        "model": model or "",
        "image_shapes": _img_shapes(image_b64),
    }
    if temperature != DEFAULT_TEMPERATURE:
        payload["temperature"] = temperature
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def load_alias_index(cache_dir) -> dict:
    """{alias_key: exact_key}, or {} when there is no usable index."""
    try:
        data = json.loads((Path(cache_dir) / ALIAS_INDEX_FILE)
                          .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    aliases = data.get("aliases") if isinstance(data, dict) else None
    return dict(aliases) if isinstance(aliases, dict) else {}


def write_alias_index(cache_dir, aliases: dict, report: Optional[dict] = None) -> None:
    body = {"version": 1,
            "note": "alias key -> exact key, native-text requests only; built by "
                    "python -m tests.harness.alias_index on the recording machine",
            "report": report or {},
            "aliases": dict(sorted(aliases.items()))}
    (Path(cache_dir) / ALIAS_INDEX_FILE).write_text(
        json.dumps(body, indent=1) + "\n", encoding="utf-8")


def build_alias_index(entries) -> tuple:
    """From trace entries ({exact, alias, native, hit}) to (index, report).

    Only EXACT HITS of NATIVE-TEXT requests qualify — a hit proves the entry
    answers this very request on the recording machine. An alias that two
    different exact keys share is ambiguous and left out: serving either
    would be a guess."""
    by_alias: dict = {}
    excluded = set()
    for e in entries:
        if not e.get("hit"):
            continue
        if e.get("native") is not True:
            excluded.add(e["exact"])
            continue
        by_alias.setdefault(e["alias"], set()).add(e["exact"])
    index = {a: next(iter(ks)) for a, ks in by_alias.items() if len(ks) == 1}
    aliased = set(index.values())
    report = {"alias_entries": len(index),
              "ambiguous_aliases": sum(1 for ks in by_alias.values() if len(ks) > 1),
              "ocr_or_unknown": len(excluded - aliased)}
    return index, report


def replay_misses_are_fatal(cache) -> None:
    """A replay run with a miss has scored a document on an answer it never
    got (the engine turns the miss into a failed call). Refuse to report it."""
    misses = cache.stats.get("misses", 0)
    if cache.mode == "replay" and misses:
        raise SystemExit(
            f"REPLAY INCOMPLETE: {misses} request(s) had no recorded answer "
            f"(exact or alias), so the scores would count unanswered documents "
            f"as wrong. Nothing is reported. Re-record, or see "
            f"docs/proposals/replay-portability.md.")


#: Tracing (DOCAGENT_CACHE_TRACE=<file>) for building the alias index: each
#: lookup appends {exact, alias, native, hit}. `native` comes from the last
#: document this THREAD preprocessed — True when no page was OCR'd, None when
#: the request was made without one (never aliased).
_TRACE = os.environ.get("DOCAGENT_CACHE_TRACE") or None
_TRACE_LOCK = threading.Lock()
_DOC_STATE = threading.local()


def _install_native_probe() -> None:
    from core import preprocessor
    if getattr(preprocessor.preprocess_file, "_alias_probe", False):
        return
    orig = preprocessor.preprocess_file

    def probed(file_path):
        doc = orig(file_path)
        _DOC_STATE.native = not getattr(doc, "ocr_pages", None)
        return doc
    probed._alias_probe = True
    preprocessor.preprocess_file = probed


class LLMCache:
    def __init__(self, mode: str = "replay", cache_dir=None):
        assert mode in ("record", "replay", "live"), mode
        self.dir = cache_dir or CACHE_DIR
        self._mode = mode
        self.context = ""  # e.g. current document id, stored in meta
        self.stats = {"hits": 0, "alias_hits": 0, "recorded": 0, "live": 0,
                      "misses": 0}
        self._aliases = None          # loaded on first use
        self._render_ok = None        # None until the preflight has run
        self._render_error = None
        self.calls = []  # (method, key, source) in call order
        self._orig = {}

    #: Entering replay runs the preflight (once per process per directory),
    #: however it is entered: constructed in replay, installed in replay, or
    #: switched into replay after being installed in another mode. `_dispatch`
    #: checks again before any replay lookup, so no path reaches the cache
    #: unchecked.
    @property
    def mode(self) -> str:
        return self._mode

    @mode.setter
    def mode(self, value: str) -> None:
        assert value in ("record", "replay", "live"), value
        self._mode = value
        if value == "replay" and self._orig:
            self._preflight()

    def _preflight(self) -> None:
        """The render check. With an alias index a mismatch is not fatal here:
        native-text requests can still replay by alias, and a request that
        cannot raises the same named error when it is looked up."""
        try:
            ensure_replay_environment(self.dir)
            self._render_ok = True
        except ReplayEnvironmentError as exc:
            if not self._alias_index():
                raise
            self._render_ok = False
            self._render_error = exc

    def _alias_index(self) -> dict:
        if self._aliases is None:
            self._aliases = load_alias_index(self.dir)
        return self._aliases

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
        from connectors.base import LLMResponse
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
        # The offline stub provider (connectors/stub_client.py) is a pure
        # function of the prompt: nothing to record, nothing to replay.
        if [n for n, _ in getattr(router, "providers", [])][:1] == ["stub"]:
            return orig(router, **kwargs)
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
        if self.mode == "replay" and self._render_ok is None:
            self._preflight()
        alias = None
        if self.mode == "replay" or _TRACE:
            alias = alias_key(method, text=kwargs.get("text", ""),
                              image_b64=kwargs.get("image_b64", ""),
                              prompt=kwargs.get("prompt", ""),
                              system_instruction=kwargs.get("system_instruction", ""),
                              model=kwargs.get("model"),
                              temperature=kwargs.get("temperature",
                                                     DEFAULT_TEMPERATURE))
        if self.mode != "live":
            # Exact key first, then the alias. DOCAGENT_REPLAY_ALIAS_ONLY=1
            # serves every indexed request by its alias, which is how the alias
            # path is proved on the recording machine.
            aliased = self.mode == "replay" and alias in self._alias_index()
            alias_only = aliased and os.environ.get("DOCAGENT_REPLAY_ALIAS_ONLY") == "1"
            cached = None if alias_only else self._load(key)
            if cached is not None:
                self.stats["hits"] += 1
                self.calls.append((method, key, "cache"))
                self._trace(key, alias, True)
                return self._to_response(cached)
            if aliased:
                cached = self._load(self._alias_index()[alias])
                if cached is not None:
                    self.stats["alias_hits"] += 1
                    self.calls.append((method, key, "alias"))
                    return self._to_response(cached)
            self._trace(key, alias, False)

        if self.mode == "replay":
            self.stats["misses"] += 1
            if self._render_ok is False:
                raise ReplayEnvironmentError(
                    f"{self._render_error} This request has no alias (an OCR'd "
                    f"page, or never indexed), so it needs the recording "
                    f"machine's render.")
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

    def _trace(self, key: str, alias: Optional[str], hit: bool) -> None:
        if not _TRACE or alias is None:
            return
        rec = {"exact": key, "alias": alias, "hit": hit,
               "native": getattr(_DOC_STATE, "native", None)}
        with _TRACE_LOCK, open(_TRACE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    # ── install / uninstall ──────────────────────────────────────────────────

    def install(self) -> None:
        bootstrap()
        from connectors.llm_router import LLMRouter

        if self.mode == "replay":
            self._preflight()
        if _TRACE:
            _install_native_probe()

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
