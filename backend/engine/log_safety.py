"""What a log line may carry (docs/SECURITY.md, "Logging").

Logs leave the tenant boundary: they go to the platform's log drain, to
whoever debugs a deploy, to a screenshot in a chat. So a line names a document
by an opaque reference, an error by its type, and a run by its counts and
timings — never by the document's text, its extracted values, the file name a
client gave it, a prompt or a model answer.

`doc_ref` is a stable hash of the file's base name: the same file gives the
same reference in every line of a run, and someone holding the database (where
the real name is stored) can recompute it to find the row. It cannot be read
back into the name.
"""
from __future__ import annotations

import hashlib
import sys
import traceback
from pathlib import PurePath


def _utf8(stream) -> bool:
    enc = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
    return enc in ("utf8", "utf8sig")


def safe_stdio() -> None:
    """Make stdout/stderr REPLACE what they cannot encode instead of raising
    (Review-3 F12).

    On a Windows console (or a pipe) with a CP1252 code page, printing the
    orchestrator's startup panel — box drawing and an emoji — raised
    UnicodeEncodeError and took worker startup down with it, so every job
    failed before its first document. Output is for people; a character it
    cannot show becomes `?`, it never stops the work. A UTF-8 stream is left
    alone. Idempotent; a stream without `reconfigure` (a test's capture) is
    left as it is."""
    for stream in (sys.stdout, sys.stderr):
        if stream is None or _utf8(stream) or not hasattr(stream, "reconfigure"):
            continue
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError, OSError):
            continue


class ReplacingStdout:
    """A file for Rich: writes to whatever `sys.stdout` is NOW, replacing any
    character its encoding cannot hold. Rich keeps a reference to its file,
    so this proxy is what lets the orchestrator's module-level Console survive
    a non-UTF-8 stream (and a test swapping sys.stdout)."""

    @property
    def _s(self):
        return sys.stdout

    @property
    def encoding(self):
        return getattr(self._s, "encoding", None) or "utf-8"

    def write(self, text):
        s = self._s
        if s is None:
            return 0
        if not _utf8(s):
            enc = getattr(s, "encoding", None) or "ascii"
            text = text.encode(enc, "replace").decode(enc, "replace")
        return s.write(text)

    def flush(self):
        if self._s is not None:
            self._s.flush()

    def isatty(self):
        try:
            return bool(self._s.isatty())
        except Exception:
            return False

    def fileno(self):
        return self._s.fileno()


def doc_ref(name) -> str:
    """`doc-1a2b3c4d5e` for a file name, path or storage key."""
    if not name:
        return "doc-none"
    base = PurePath(str(name).replace("\\", "/")).name or str(name)
    return "doc-" + hashlib.sha256(base.encode("utf-8", "replace")).hexdigest()[:10]


def exc_brief(e: BaseException) -> str:
    """An exception as a reason code: its type, and an HTTP status if it has
    one. Never its message — messages quote file names, paths, and whatever
    text a parser choked on."""
    name = type(e).__name__
    for attr in ("code", "status_code", "status"):
        v = getattr(e, attr, None)
        if isinstance(v, int):
            return f"{name}({v})"
    return name


def print_safe_traceback(e: BaseException | None = None, file=None) -> None:
    """`traceback.print_exc()` without the message: every frame's file, line
    and function, then the exception's type. Enough to find the bug; nothing
    from the document."""
    if e is None:
        e = sys.exc_info()[1]
    if e is None:
        return
    print(safe_traceback_text(e), file=file or sys.stderr, flush=True)


def safe_traceback_text(e: BaseException) -> str:
    """The frames-only traceback as one string, for a logger call."""
    lines = ["Traceback (frames only; message withheld by log policy):"]
    for fs in traceback.extract_tb(e.__traceback__):
        lines.append(f"  {PurePath(fs.filename).name}:{fs.lineno} in {fs.name}")
    lines.append(exc_brief(e))
    return "\n".join(lines)


#: Libraries that read the document and log what they read below WARNING —
#: pdfminer's DEBUG tokens are the page's text, verbatim. Capped at WARNING
#: whatever the root level is, so turning on DEBUG to chase a bug does not
#: start writing documents into the log drain.
THIRD_PARTY_READERS = ("pdfminer", "pdfplumber", "PIL", "pypdf", "pytesseract",
                       "pdf2image", "urllib3", "botocore", "boto3", "s3transfer")


def quiet_document_readers() -> None:
    import logging
    for name in THIRD_PARTY_READERS:
        lg = logging.getLogger(name)
        if lg.level == logging.NOTSET or lg.level < logging.WARNING:
            lg.setLevel(logging.WARNING)


quiet_document_readers()
