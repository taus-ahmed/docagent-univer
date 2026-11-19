"""Hard cap for live Gemini calls in a measurement session (Run B, B0/B7).

Patches ``GeminiClient._post`` - the single HTTP request every engine call,
retry and model-discovery step goes through - so the cap counts requests that
actually leave the machine, not engine-level "calls". Before every request it
prints the call number and running estimated cost, and refuses once either
limit is reached. A request that fails still counts.

The counter lives in a JSON state file so several processes in one session
share one cap. The API key is never read here; the client reads it from the
environment as usual, and nothing here prints or stores it.

Usage:
    from tests.tools import live_cap
    live_cap.install(state_file)          # before any engine call
    ...
    live_cap.summary()
"""
from __future__ import annotations

import json
import time
from pathlib import Path

MAX_CALLS = 12
MAX_USD = 1.00
# USD per million tokens, Gemini 2.5 Flash (owner's table). Thinking tokens
# are billed as output.
PRICE_IN = 0.30
PRICE_OUT = 2.50
# Used when a request reports no usage (it failed): a pessimistic charge so a
# run of failures cannot slip past the cost cap.
FAILED_CALL_USD = 0.02


class CapReached(BaseException):
    """BaseException on purpose: engine code catches ``Exception`` in places,
    and a refused call must stop the measurement, not become a retry."""


_STATE: Path | None = None
_LABEL = ""


def _load() -> dict:
    if _STATE and _STATE.exists():
        return json.loads(_STATE.read_text(encoding="utf-8"))
    return {"calls": 0, "usd": 0.0, "log": []}


def _save(state: dict) -> None:
    _STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def cost_of(prompt_tokens, output_tokens, thinking_tokens) -> float:
    return ((prompt_tokens or 0) * PRICE_IN
            + ((output_tokens or 0) + (thinking_tokens or 0)) * PRICE_OUT) / 1e6


def install(state_file, label: str = "") -> None:
    global _STATE, _LABEL
    _STATE = Path(state_file)
    _LABEL = label
    from connectors.gemini_client import GeminiClient

    if getattr(GeminiClient._post, "_capped", False):
        return
    real_post = GeminiClient._post

    def capped_post(self, model, body, timeout):
        state = _load()
        if state["calls"] >= MAX_CALLS:
            print(f"[LIVE-CAP] REFUSED: {state['calls']} of {MAX_CALLS} calls used",
                  flush=True)
            raise CapReached("call cap")
        if state["usd"] >= MAX_USD:
            print(f"[LIVE-CAP] REFUSED: ${state['usd']:.4f} >= ${MAX_USD:.2f}",
                  flush=True)
            raise CapReached("cost cap")
        n = state["calls"] + 1
        print(f"[LIVE-CAP] call {n}/{MAX_CALLS} model={model} "
              f"running cost ${state['usd']:.4f} {_LABEL}", flush=True)
        state["calls"] = n
        entry = {"n": n, "model": model, "label": _LABEL, "ok": False}
        state["log"].append(entry)
        _save(state)                     # counted BEFORE the request goes out
        t0 = time.monotonic()
        try:
            text, info = real_post(self, model, body, timeout)
        except BaseException as e:
            state = _load()
            state["usd"] += FAILED_CALL_USD
            state["log"][-1].update(error=type(e).__name__,
                                    kind=getattr(e, "kind", None),
                                    latency_ms=round((time.monotonic() - t0) * 1000),
                                    usd=FAILED_CALL_USD)
            _save(state)
            raise
        usd = cost_of(info.get("prompt_tokens"), info.get("output_tokens"),
                      info.get("thinking_tokens"))
        state = _load()
        state["usd"] += usd
        state["log"][-1].update(
            ok=True, usd=round(usd, 6),
            latency_ms=round((time.monotonic() - t0) * 1000),
            finish_reason=info.get("finish_reason"),
            prompt_tokens=info.get("prompt_tokens"),
            output_tokens=info.get("output_tokens"),
            thinking_tokens=info.get("thinking_tokens"),
            response_chars=len(text or ""))
        _save(state)
        return text, info

    capped_post._capped = True
    GeminiClient._post = capped_post


def set_label(label: str) -> None:
    global _LABEL
    _LABEL = label


def summary() -> dict:
    state = _load()
    print(f"[LIVE-CAP] total {state['calls']}/{MAX_CALLS} calls, "
          f"${state['usd']:.4f} of ${MAX_USD:.2f}", flush=True)
    return state
