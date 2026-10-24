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
