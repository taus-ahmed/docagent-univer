"""Request ids, a safe access log, and JSON logs (Part 2.8).

* Every request gets an id: the caller's `X-Request-ID` when it is a plain
  token (8-64 letters, digits, '-' or '_'), else a new one. It is returned in
  the `X-Request-ID` response header and stamped on every log record made
  while the request runs (`request_id`), so one request's lines can be found.
* The access log is ours, not uvicorn's: method, PATH ONLY, status, time and
  request id. A query string can carry a token or a document name, so it is
  never logged; uvicorn's own access log is switched off
  (backend/docker-entrypoint.sh, --no-access-log).
* `LOG_FORMAT=json` writes one JSON object per line ({ts, level, logger,
  request_id, msg}) for a log drain; `text` (default) stays human-readable.

What a log line may carry is unchanged (engine/log_safety.py): ids, counts,
reason codes — never document text, file names, tokens or secrets.
"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextvars import ContextVar

REQUEST_ID: ContextVar = ContextVar("request_id", default="-")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
access_log = logging.getLogger("docagent.access")


class RequestIdFilter(logging.Filter):
    def filter(self, record):
        record.request_id = REQUEST_ID.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record):
        out = {"ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
               "level": record.levelname, "logger": record.name,
               "request_id": getattr(record, "request_id", "-"),
               "msg": record.getMessage()}
        if record.exc_info:
            out["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else ""
        return json.dumps(out, ensure_ascii=False)


TEXT_FORMAT = "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s"


def configure_logging(fmt: str = "text") -> None:
    """One handler on the root logger, with the request-id filter."""
    root = logging.getLogger()
    handler = next((h for h in root.handlers if getattr(h, "_docagent", False)), None)
    if handler is None:
        handler = logging.StreamHandler()
        handler._docagent = True
        for h in list(root.handlers):
            root.removeHandler(h)
        root.addHandler(handler)
    handler.filters = [RequestIdFilter()]
    handler.setFormatter(JsonFormatter() if str(fmt).lower() == "json"
                         else logging.Formatter(TEXT_FORMAT))
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)


def request_id_for(header_value) -> str:
    v = str(header_value or "").strip()
    return v if _SAFE_ID.match(v) else uuid.uuid4().hex


async def request_id_middleware(request, call_next):
    rid = request_id_for(request.headers.get("x-request-id"))
    token = REQUEST_ID.set(rid)
    t0 = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        return response
    finally:
        access_log.info("%s %s %s %.0fms", request.method, request.url.path, status,
                        (time.perf_counter() - t0) * 1000)
        REQUEST_ID.reset(token)
