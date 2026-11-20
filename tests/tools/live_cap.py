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


#: Overnight M3: the caps may be SET from the environment (LIVE_CAP_MAX_CALLS,
#: LIVE_CAP_MAX_USD) but never removed: a value must be a positive, finite
#: number under these ceilings, or the run refuses to start.
HARD_CEILING_CALLS = 200
HARD_CEILING_USD = 5.00


def limits() -> tuple:
    """(max calls, max USD) for this session — the environment's values,
    validated, else MAX_CALLS / MAX_USD. Raises ValueError rather than ever
    returning an unlimited cap."""
    import math
    import os
    raw_c = os.environ.get("LIVE_CAP_MAX_CALLS")
    raw_u = os.environ.get("LIVE_CAP_MAX_USD")
    try:
        calls = MAX_CALLS if raw_c is None else int(float(raw_c))
        usd = MAX_USD if raw_u is None else float(raw_u)
    except (TypeError, ValueError, OverflowError):
        raise ValueError("LIVE_CAP_MAX_CALLS / LIVE_CAP_MAX_USD must be finite numbers")
    if raw_c is not None and (not math.isfinite(float(raw_c))):
        raise ValueError("LIVE_CAP_MAX_CALLS must be finite")
    if not 1 <= calls <= HARD_CEILING_CALLS:
        raise ValueError(f"LIVE_CAP_MAX_CALLS must be 1..{HARD_CEILING_CALLS}")
    if not (math.isfinite(usd) and 0 < usd <= HARD_CEILING_USD):
        raise ValueError(f"LIVE_CAP_MAX_USD must be > 0 and <= {HARD_CEILING_USD}")
    return calls, usd


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


def cost_of(prompt_tokens, output_tokens, thinking_tokens, model=None) -> float:
    """USD for one request: the engine's price table for `model` when it has
    one (llm_contract.cost_estimate), else the Gemini 2.5 Flash rates."""
    if model:
        try:
            import llm_contract as C
            est = C.cost_estimate(prompt_tokens, output_tokens, thinking_tokens, model)
            if est is not None:
                return est
        except Exception:
            pass
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

    max_calls, max_usd = limits()      # validated once, at install

    def capped_post(self, model, body, timeout):
        MAX_CALLS, MAX_USD = max_calls, max_usd  # noqa: N806 (the caps in force)
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
                      info.get("thinking_tokens"), info.get("model_version") or model)
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
    calls, usd = limits()
    print(f"[LIVE-CAP] total {state['calls']}/{calls} calls, "
          f"${state['usd']:.4f} of ${usd:.2f}", flush=True)
    return state
