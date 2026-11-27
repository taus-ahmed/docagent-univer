"""
The model's answer is UNTRUSTED until validated (Run A, A0 + A2).

Three things live here, all model-independent:

1. ATTEMPT RECORDS. One dict per HTTP attempt at the model, stored on the
   document (`extracted_data["diagnostics"]["attempts"]`) and logged as one
   redacted line. A record carries counts and identifiers only: no document
   text, no extracted value, no key. A counter the API did not return is
   `None`, never 0 — "not reported" and "zero" are different answers.

2. COST. `cost_estimate` prices an attempt by the model the API SAYS answered
   (`modelVersion`), not the model that was asked for, from a table that
   `LLM_PRICE_TABLE` can override. Thinking tokens are billed as output.

3. THE RESPONSE CONTRACT. `response_schema(slots)` asks Gemini for structured
   output in which every requested slot id and every table key is REQUIRED;
   `check_answer` validates the parsed answer anyway, because a schema is a
   request and the answer is evidence. Every failure is TYPED — a missing
   `tables` key is `missing_table`, not an empty table.

Job 15 (flowparse_bank_us.pdf) is the reason for (3): one call returned valid
JSON holding `fields` F1..F8 and no `tables` key at all, and the pipeline read
the absence as "no rows" — an empty success.
"""
from __future__ import annotations

import contextvars
import json
import re
import time
from typing import Optional

# ── who is calling (set by the job worker; logs only) ────────────────────────
#: {"job_id": ..., "document": ...} for the job thread currently extracting.
#: Read by the attempt log line. Never holds document content.
CALL_CONTEXT: contextvars.ContextVar = contextvars.ContextVar(
    "docagent_call_context", default={})
#: The section an attempt is for ("fields+tables", "retry:table", "page 3").
CALL_SECTION: contextvars.ContextVar = contextvars.ContextVar(
    "docagent_call_section", default="")
#: Every attempt record made in this context, appended by the provider.
#: A list object per document, installed by `collect_attempts`.
ATTEMPTS: contextvars.ContextVar = contextvars.ContextVar(
    "docagent_attempts", default=None)


class collect_attempts:
    """`with collect_attempts() as attempts:` — every model attempt made
    inside the block is appended to `attempts`. Nested blocks share the
    outer list, so a document's attempts include its inference call."""

    def __init__(self, fresh: bool = False):
        self.fresh = fresh

    def __enter__(self):
        outer = ATTEMPTS.get()
        self.list = outer if (outer is not None and not self.fresh) else []
        self._tok = ATTEMPTS.set(self.list)
        return self.list

    def __exit__(self, *exc):
        ATTEMPTS.reset(self._tok)
        return False


class section:
    """`with section("retry:table"):` labels the attempts made inside it."""

    def __init__(self, name: str):
        self.name = name

    def __enter__(self):
        self._tok = CALL_SECTION.set(self.name)

    def __exit__(self, *exc):
        CALL_SECTION.reset(self._tok)
        return False


# ── typed failures ───────────────────────────────────────────────────────────
# Transport / provider
TRANSIENT = "transient"              # timeout, connection reset, 429 rate, 5xx
QUOTA = "quota_exhausted"            # 429 whose body names a daily/project quota
INVALID_REQUEST = "invalid_request"  # 400: our request is wrong; never retried
AUTH = "auth"                        # 401/403
MODEL_NOT_FOUND = "model_not_found"  # 404
# Answer
NO_CANDIDATE = "no_candidate"
BLOCKED = "blocked"                  # promptFeedback.blockReason / SAFETY etc.
MAX_TOKENS = "max_tokens"
EMPTY = "empty"                      # empty / whitespace / {}
INVALID_JSON = "invalid_json"
# Contract (the answer parsed, and is incomplete)
MISSING_SLOT = "missing_slot"
MISSING_TABLE = "missing_table"
EMPTY_TABLE = "empty_table"          # present, [] , while the page shows rows

#: failures a retry of the SAME request may fix
RETRYABLE_TRANSPORT = {TRANSIENT}
#: failures no retry may touch
NEVER_RETRY = {QUOTA, INVALID_REQUEST, AUTH, BLOCKED}


class LLMCallError(Exception):
    """A provider call that failed in a known way. `kind` is one of the
    constants above; `retry_after` is seconds when the server said so."""

    def __init__(self, kind: str, message: str = "", status: Optional[int] = None,
                 retry_after: Optional[float] = None, api_status: Optional[str] = None,
                 api_reason: Optional[str] = None, cause: Optional[str] = None):
        super().__init__(message or kind)
        self.kind = kind
        self.status = status
        self.retry_after = retry_after
        # Run T, 11: what the provider SAID, without its words. `api_status`
        # is its status name (INVALID_ARGUMENT), `api_reason` an ErrorInfo
        # reason code, `cause` one word from CAUSES. The message itself can
        # quote the request (a template's labels), so it is never kept.
        self.api_status = api_status
        self.api_reason = api_reason
        self.cause = cause


#: Run T, 11 — the cause of a refused request, read from the provider's
#: message by pattern and kept as ONE WORD. Order matters: the first match
#: wins.
CAUSES = (
    ("schema", r"response_?schema|responseSchema|too many states|schema"),
    ("input_too_long", r"token count|too many tokens|exceeds the maximum|input.*too long|request payload size"),
    ("image", r"inline_?data|mime|image|base64"),
    ("generation_config", r"generation_?config|thinking|temperature|max_?output_?tokens"),
    ("api_key", r"api[ _]?key"),
    ("model", r"model"),
)

#: words for a cause in a sentence a person reads (failure_story)
CAUSE_WORDS = {
    "schema": "the answer format was too large or not accepted",
    "input_too_long": "the request was too long",
    "image": "a page image was not accepted",
    "generation_config": "a request setting was not accepted",
    "api_key": "the API key was not accepted",
    "model": "the model was not accepted",
}


def classify_cause(message: str) -> Optional[str]:
    m = str(message or "")
    for name, pat in CAUSES:
        if re.search(pat, m, re.IGNORECASE):
            return name
    return None


def schema_size(schema) -> dict:
    """{fields, tables, columns} of a response schema built by
    `response_schema`; zeros for none."""
    props = (schema or {}).get("properties") or {}
    fields = len(((props.get("fields") or {}).get("properties")) or {})
    tprops = ((props.get("tables") or {}).get("properties")) or {}
    cols = 0
    for t in tprops.values():
        cells = (((t.get("items") or {}).get("properties") or {}).get("cells") or {})
        cols += len(cells.get("properties") or {})
    return {"fields": fields, "tables": len(tprops), "columns": cols}


# ── settings (read lazily; the engine may run without app settings) ──────────

def setting(name: str, default):
    try:
        from config import settings
        v = getattr(settings, name, default)
        return default if v is None and default is not None else v
    except Exception:
        return default


# ── cost ─────────────────────────────────────────────────────────────────────

#: USD per 1M tokens. Keys are model-name PREFIXES; the longest match wins, so
#: "gemini-2.5-flash-lite" is not priced as "gemini-2.5-flash". Published
#: Gemini Developer API list prices (text/image input, standard tier); the
#: operator can override any of them with LLM_PRICE_TABLE.
DEFAULT_PRICES = {
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    "gemini-2.5-flash-lite": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gemini-2.0-flash-lite": {"input": 0.075, "output": 0.30},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-flash-lite-latest": {"input": 0.10, "output": 0.40},
    "gemini-flash-latest": {"input": 0.30, "output": 2.50},
    # Overnight M3, Google's model pages read 2026-11-20 (docs/MODEL_MIGRATION.md).
    # gemini-3.8-flash is $0.75 / $3.75 introductory until 2026-12-31; the
    # STANDARD rate is listed so a cost cap never under-counts.
    "gemini-3.5-flash-lite": {"input": 0.30, "output": 2.50},
    "gemini-3.6-flash": {"input": 1.50, "output": 7.50},
    "gemini-3.8-flash": {"input": 1.50, "output": 7.50},
}


def price_table() -> dict:
    table = dict(DEFAULT_PRICES)
    raw = str(setting("LLM_PRICE_TABLE", "") or "").strip()
    if raw:
        try:
            extra = json.loads(raw)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    if isinstance(v, dict) and {"input", "output"} <= set(v):
                        table[str(k)] = {"input": float(v["input"]),
                                         "output": float(v["output"])}
        except (ValueError, TypeError):
            pass
    return table


def price_for(model: Optional[str]) -> Optional[dict]:
    m = str(model or "").replace("models/", "").strip().lower()
    if not m:
        return None
    best = None
    for key, p in price_table().items():
        if m.startswith(key.lower()) and (best is None or len(key) > len(best[0])):
            best = (key, p)
    return best[1] if best else None


def cost_estimate(prompt_tokens, output_tokens, thinking_tokens,
                  model) -> Optional[float]:
    """USD, or None when the model is not priced or no counter came back."""
    p = price_for(model)
    if p is None or (prompt_tokens is None and output_tokens is None):
        return None
    inp = prompt_tokens or 0
    out = (output_tokens or 0) + (thinking_tokens or 0)
    return round(inp / 1e6 * p["input"] + out / 1e6 * p["output"], 6)


def total_tokens(prompt_tokens, output_tokens, thinking_tokens) -> Optional[int]:
    """Tokens billed for one attempt, INCLUDING thinking. None when the API
    reported no counter at all."""
    parts = [prompt_tokens, output_tokens, thinking_tokens]
    if all(p is None for p in parts):
        return None
    return sum(p or 0 for p in parts)


# ── attempt records ──────────────────────────────────────────────────────────

def new_attempt(model_requested: str, retry: int = 0, reason: str = "",
                images: int = 0) -> dict:
    return {
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "section": CALL_SECTION.get() or "",
        "model_requested": model_requested,
        "model_version": None,
        "finish_reason": None,
        "candidate_count": None,
        "response_chars": None,
        "prompt_tokens": None,
        "output_tokens": None,
        "thinking_tokens": None,
        "total_tokens": None,
        "cost_estimate": None,
        "latency_ms": None,
        "images": images,
        "http_status": None,
        "parse": None,           # ok | invalid_json | empty | not_attempted
        "error_kind": None,
        "retry": retry,
        "retry_reason": reason or None,
        "structured_output": None,
        "schema_fields": None, "schema_columns": None,
        "api_status": None, "api_reason": None, "cause": None,
        "slots_requested": None, "slots_returned": None,
        "tables_requested": None, "tables_returned": None,
    }


def finish_attempt(rec: dict, log: bool = True) -> dict:
    """Fill the derived counters, store the record, and log it (redacted).
    `log=False` when the caller logs it later, once the parse result is
    known."""
    rec["total_tokens"] = total_tokens(rec["prompt_tokens"], rec["output_tokens"],
                                       rec["thinking_tokens"])
    rec["cost_estimate"] = cost_estimate(
        rec["prompt_tokens"], rec["output_tokens"], rec["thinking_tokens"],
        rec["model_version"] or rec["model_requested"])
    sink = ATTEMPTS.get()
    if sink is not None:
        sink.append(rec)
    if log:
        log_attempt(rec)
    return rec


def log_attempt(rec: dict) -> None:
    ctx = CALL_CONTEXT.get() or {}
    keys = ("section", "model_requested", "model_version", "finish_reason",
            "candidate_count", "response_chars", "prompt_tokens",
            "output_tokens", "thinking_tokens", "cost_estimate", "latency_ms",
            "images", "http_status", "api_status", "api_reason", "cause",
            "parse", "error_kind", "retry", "retry_reason", "structured_output",
            "schema_fields", "schema_columns", "slots_requested", "slots_returned",
            "tables_requested", "tables_returned")
    body = " ".join(f"{k}={rec.get(k)}" for k in keys)
    print(f"[LLM-ATTEMPT] job={ctx.get('job_id')} doc={ctx.get('document')} "
          f"pages={ctx.get('pages')} {body}", flush=True)


def note_contract(rec_list, requested_slots, returned_slots,
                  requested_tables, returned_tables) -> None:
    """Write slots/tables requested vs returned onto the LAST attempt record
    (the one whose answer was parsed)."""
    if not rec_list:
        return
    rec = rec_list[-1]
    rec["slots_requested"] = requested_slots
    rec["slots_returned"] = returned_slots
    rec["tables_requested"] = requested_tables
    rec["tables_returned"] = returned_tables


def failure_story(attempts, timeout_s=None) -> str:
    """Run R, R4: why a document's extraction call failed, in words, from its
    own attempts - status, kind and latency only, never content. Job 133
    reads: "the model service refused this template's answer format (HTTP
    400); asked again without it, the call timed out after 120 s, twice"."""
    if timeout_s is None:
        try:
            timeout_s = float(setting("LLM_CALL_TIMEOUT_S", 120.0))
        except Exception:
            timeout_s = 120.0
    steps = []
    for a in attempts or []:
        if not isinstance(a, dict) or not a.get("error_kind"):
            continue
        kind, st = a.get("error_kind"), a.get("http_status")
        lat = (a.get("latency_ms") or 0) / 1000.0
        why = CAUSE_WORDS.get(a.get("cause") or "")
        if kind == INVALID_REQUEST and a.get("structured_output"):
            s = f"the model service refused this template's answer format (HTTP {st or 400})"
        elif kind == INVALID_REQUEST:
            s = (f"the model service refused the request (HTTP {st or 400}: {why})"
                 if why else f"the model service refused the request (HTTP {st or 400})")
        elif kind == TRANSIENT and st is None and timeout_s and lat >= 0.9 * timeout_s:
            s = f"the call timed out after {int(round(timeout_s))} s"
        elif kind == TRANSIENT:
            s = f"the model service did not answer (HTTP {st})" if st else \
                "the connection failed"
        elif kind == QUOTA:
            s = "the model service's quota was exhausted"
        else:
            s = f"the call failed ({kind})"
        if a.get("retry_reason") == "schema_rejected":
            s = "asked again without it, " + s
        bare = lambda x: x.replace("asked again without it, ", "")  # noqa: E731
        if steps and bare(steps[-1][0]) == bare(s):
            steps[-1][1] += 1
            continue
        steps.append([s, 1])
    words = {2: "twice", 3: "three times"}
    out = [s + ("" if n == 1 else f", {words.get(n, f'{n} times')}") for s, n in steps]
    return "; ".join(out)


def summarise(attempts) -> dict:
    """Totals over a document's attempts. Counters stay None when no attempt
    reported them."""
    def tot(key):
        vals = [a.get(key) for a in attempts or [] if a.get(key) is not None]
        return sum(vals) if vals else None
    costs = [a.get("cost_estimate") for a in attempts or []
             if a.get("cost_estimate") is not None]
    return {
        "attempts": len(attempts or []),
        "prompt_tokens": tot("prompt_tokens"),
        "output_tokens": tot("output_tokens"),
        "thinking_tokens": tot("thinking_tokens"),
        "total_tokens": tot("total_tokens"),
        "cost_estimate": round(sum(costs), 6) if costs else None,
        "latency_ms": tot("latency_ms"),
        "models": sorted({a.get("model_version") or a.get("model_requested")
                          for a in attempts or []
                          if a.get("model_version") or a.get("model_requested")}),
    }


# ── response schema ──────────────────────────────────────────────────────────

_VALUE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "value": {"type": "STRING"},
        "source": {"type": "STRING"},
        "page": {"type": "INTEGER"},
        "status": {"type": "STRING", "enum": ["found", "absent", "unreadable"]},
    },
    "required": ["value", "source", "page", "status"],
    "propertyOrdering": ["value", "source", "page", "status"],
}


def response_schema(slots, headers_of) -> dict:
    """A Gemini `responseSchema` making EVERY slot id and EVERY table key
    required. `headers_of(table)` gives a table's answer keys."""
    fields = slots.get("fields") or []
    tables = slots.get("tables") or []
    props, required = {}, []
    if fields:
        ids = [f["slot_id"] for f in fields]
        props["fields"] = {"type": "OBJECT",
                           "properties": {i: _VALUE_SCHEMA for i in ids},
                           "required": ids, "propertyOrdering": ids}
        required.append("fields")
    if tables:
        tprops = {}
        for t in tables:
            heads = list(dict.fromkeys(headers_of(t)))
            tprops[t["name"]] = {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "cells": {"type": "OBJECT",
                                  "properties": {h: {"type": "STRING"} for h in heads},
                                  "required": heads, "propertyOrdering": heads},
                        "source": {"type": "STRING"},
                        "page": {"type": "INTEGER"},
                    },
                    "required": ["cells", "source", "page"],
                    "propertyOrdering": ["cells", "source", "page"],
                },
            }
        names = [t["name"] for t in tables]
        props["tables"] = {"type": "OBJECT", "properties": tprops,
                           "required": names, "propertyOrdering": names}
        required.append("tables")
    return {"type": "OBJECT", "properties": props, "required": required,
            "propertyOrdering": required}


# ── validation ───────────────────────────────────────────────────────────────

def failure(kind: str, detail: str = "", slots=(), tables=()) -> dict:
    return {"kind": kind, "detail": detail, "slots": list(slots),
            "tables": list(tables)}


def _table_answer(resp_tables: dict, t: dict, n_tables: int):
    if not isinstance(resp_tables, dict):
        return None
    raw = resp_tables.get(t["name"])
    if raw is None and n_tables == 1 and len(resp_tables) == 1:
        raw = next(iter(resp_tables.values()))      # the model renamed it
    return raw


def check_answer(parsed, slots, resp=None, expected_rows=None) -> list:
    """Typed failures for one parsed answer, before anything becomes a cell.

    `expected_rows` is {table name: candidate rows on the page(s)} from the
    source inventory; a table that came back `[]` while the inventory shows
    rows is EMPTY_TABLE. A table the inventory knows nothing about is never
    called empty on that ground.
    """
    out = []
    kind = getattr(resp, "error_kind", None) if resp is not None else None
    if parsed is None:
        out.append(failure(kind or INVALID_JSON,
                           str(getattr(resp, "error", "") or "")[:200]))
        return out
    if not isinstance(parsed, dict) or not parsed:
        out.append(failure(EMPTY, "the answer is empty"))
        return out
    fields = slots.get("fields") or []
    tables = slots.get("tables") or []
    ans = parsed.get("fields")
    ans = ans if isinstance(ans, dict) else {}
    keys = {str(k).strip() for k in ans}
    missing = [f["slot_id"] for f in fields if f["slot_id"] not in keys]
    if missing:
        out.append(failure(MISSING_SLOT,
                           f"{len(missing)} of {len(fields)} slot id(s) absent "
                           f"from the answer", slots=missing))
    resp_tables = parsed.get("tables")
    for t in tables:
        raw = _table_answer(resp_tables, t, len(tables))
        if not isinstance(raw, list):
            out.append(failure(MISSING_TABLE,
                               f'table "{t["name"]}" absent from the answer',
                               tables=[t["name"]]))
        elif not raw and (expected_rows or {}).get(t["name"], 0) > 0:
            out.append(failure(EMPTY_TABLE,
                               f'table "{t["name"]}" came back empty while the '
                               f'page shows about {expected_rows[t["name"]]} '
                               f"candidate row(s)", tables=[t["name"]]))
    return out


def counts(parsed, slots):
    """(slots requested, slots returned, tables requested, tables returned)."""
    fields = slots.get("fields") or []
    tables = slots.get("tables") or []
    if not isinstance(parsed, dict):
        return len(fields), 0, len(tables), 0
    ans = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    ids = {f["slot_id"] for f in fields}
    got = sum(1 for k in ans if str(k).strip() in ids)
    rt = parsed.get("tables")
    tgot = sum(1 for t in tables
               if isinstance(_table_answer(rt, t, len(tables)), list))
    return len(fields), got, len(tables), tgot


def merge_answers(first: dict, second: dict, slot_ids, table_names) -> dict:
    """`first` with the retried slots/tables taken from `second`. Only what
    was asked for again is taken; nothing in `first` is overwritten except an
    absent or empty answer."""
    out = dict(first or {})
    if slot_ids:
        f1 = dict(out.get("fields") or {}) if isinstance(out.get("fields"), dict) else {}
        f2 = (second or {}).get("fields") if isinstance((second or {}).get("fields"), dict) else {}
        for sid in slot_ids:
            if sid in f2:
                old = f1.get(sid)
                old_v = old.get("value") if isinstance(old, dict) else old
                if old is None or str(old_v or "").strip() == "":
                    f1[sid] = f2[sid]
        out["fields"] = f1
    if table_names:
        t1 = dict(out.get("tables") or {}) if isinstance(out.get("tables"), dict) else {}
        t2 = (second or {}).get("tables") if isinstance((second or {}).get("tables"), dict) else {}
        for name in table_names:
            rows = t2.get(name)
            if rows is None and len(t2) == 1 and len(table_names) == 1:
                rows = next(iter(t2.values()))
            if isinstance(rows, list) and not t1.get(name):
                t1[name] = rows
        out["tables"] = t1
    return out


_SPACE = re.compile(r"\s+")


def redact(s: str) -> str:
    """For an error string that might echo content: its length only."""
    return f"<{len(str(s or ''))} chars>"
