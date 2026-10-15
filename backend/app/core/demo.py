"""
DocAgent — demo accounts.

An investor demo is a NARROWER product than the real one, and the narrowing
has to live somewhere that cannot leak into normal use. This is that place.

THE GATE IS A CLIENT ID FROM THE TOKEN. `DEMO_CLIENT_IDS` is a comma list of
`client_id`s, empty by default, and a request is a demo request only when the
`client_id` on the authenticated user is in it. Three consequences, each
deliberate:

  * with the variable unset — the shipped default — every rule in this module
    is off for every user, so the feature cannot change behaviour for anyone
    until someone sets it;
  * the decision comes from the JWT's own tenant, never from a request body, a
    username, or a role, so a demo user cannot leave the demo by asking;
  * one more demo client is a variable change, not a code change.

What a demo account is NOT: a role, a permission level, or a security boundary.
Tenant isolation is `client_id` scoping on every query and is the same for a
demo user as for anyone else. These rules are about what the demo SHOWS.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Iterable, Optional, Sequence

from fastapi import HTTPException, status

from app.config import settings

# ── The sentence a demo user sees instead of a scanned document ───────────────
#
# Verbatim and in one place: it is shown to an investor, the wording was chosen
# by the person running the demo, and a second copy of it in a route is a copy
# that will one day say something slightly different.
SCANNED_DOC_MESSAGE = (
    "This looks like a scanned document. Scanned-document support is in "
    "development and is not part of this demo. Please try a digital PDF."
)

# Said when the demo's upload door is closed (DEMO_UPLOADS_ENABLED=false).
# Same rule as the sentence above: verbatim, once.
UPLOADS_DISABLED_MESSAGE = (
    "Uploads are disabled in this demo. Please use the sample documents."
)

#: Marks a refusal as one the DEMO MEANT TO SHOW SOMEBODY, as opposed to a
#: technical error that happens to have a status code. The Extract page replaces
#: raw error text with a neutral sentence for demo users, and without this it
#: would have to either show every message (defeating the point) or hide ours
#: too (leaving an investor with "Something went wrong" where we had written a
#: real explanation). It is a header rather than a shape inside `detail` because
#: `detail` is asserted verbatim, by tests and by the brief.
DEMO_NOTICE_HEADER = "X-Demo-Notice"

#: Where a demo client's sample documents live, relative to `backend/`. Shipped
#: in the image, read-only at runtime, and never written by a request.
SAMPLE_DOCS_DIRNAME = "demo_docs"

_BACKEND_DIR = Path(__file__).resolve().parents[2]


# ── Who is a demo user ────────────────────────────────────────────────────────

def demo_client_ids() -> frozenset[str]:
    """The configured demo tenants. Empty set when the variable is unset."""
    raw = (getattr(settings, "DEMO_CLIENT_IDS", "") or "").strip()
    if not raw:
        return frozenset()
    return frozenset(p.strip() for p in raw.split(",") if p.strip())


def is_demo_client(client_id: Optional[str]) -> bool:
    """Is this tenant a demo tenant? False for None, so an untenanted
    super-admin is never a demo user by accident."""
    if not client_id:
        return False
    return client_id in demo_client_ids()


def is_demo_user(user) -> bool:
    return is_demo_client(getattr(user, "client_id", None))


# ── B1/B2 — what a demo account may upload ────────────────────────────────────

_PDF_SUFFIX = ".pdf"

#: Everything the ordinary upload endpoint accepts that is a picture rather
#: than a document. An image has no text layer at all, so for demo purposes it
#: is the same answer as a scan — and it is the answer the user will actually
#: have in front of them, a photograph of a receipt.
_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp",
    ".webp", ".heic", ".heif", ".gif", ".avif",
}


def demo_max_bytes() -> int:
    return int(getattr(settings, "DEMO_MAX_MB", 10)) * 1024 * 1024


def demo_max_uploads() -> int:
    return int(getattr(settings, "DEMO_MAX_UPLOADS", 20))


def _demo_error(status_code: int, detail: str) -> HTTPException:
    """A refusal written FOR a demo user, tagged as such. See
    DEMO_NOTICE_HEADER."""
    return HTTPException(status_code=status_code, detail=detail,
                         headers={DEMO_NOTICE_HEADER: "1"})


def _scanned() -> HTTPException:
    return _demo_error(status.HTTP_422_UNPROCESSABLE_ENTITY,
                       SCANNED_DOC_MESSAGE)


def uploads_enabled() -> bool:
    return bool(getattr(settings, "DEMO_UPLOADS_ENABLED", True))


def check_uploads_enabled(user) -> None:
    """The demo's upload door, open or closed. A no-op for everyone else.

    Deliberately NOT part of `enforce_upload_policy`: that function is the
    shared pipeline both doors go through, and closing the upload door must
    leave the sample documents working — which is the only thing the demo has
    left when it is closed.
    """
    if not is_demo_user(user):
        return
    if not uploads_enabled():
        raise _demo_error(status.HTTP_403_FORBIDDEN, UPLOADS_DISABLED_MESSAGE)


def check_upload_quota(db, user) -> None:
    """How many jobs this demo user has already started, against the ceiling.

    Counted from `extraction_jobs` rather than a counter column, because there
    is no migration in this change and a row that exists is the only count that
    cannot drift from reality.
    """
    if not is_demo_user(user):
        return
    from app.models.models import ExtractionJob

    used = db.query(ExtractionJob).filter(
        ExtractionJob.user_id == user.id).count()
    ceiling = demo_max_uploads()
    if used >= ceiling:
        raise _demo_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"This demo account has used all {ceiling} of its extractions. "
            f"Get in touch and we will raise the limit.")


def check_demo_file(filename: str, content: bytes) -> None:
    """One file, against the demo's rules. Raises, or returns None.

    ORDER MATTERS. An image is answered with the scanned-document sentence
    rather than "PDF only", because "this is a picture of a document" is
    precisely what that sentence is about and it is the more useful of the two
    true statements.

    The text-layer question is asked LAST and only of a PDF that got this far,
    because answering it means reading the file.
    """
    suffix = Path(filename or "").suffix.lower()

    if suffix in _IMAGE_SUFFIXES:
        raise _scanned()

    if suffix != _PDF_SUFFIX:
        raise _demo_error(status.HTTP_400_BAD_REQUEST,
                          "This demo accepts PDF files only.")

    ceiling = demo_max_bytes()
    if len(content) > ceiling:
        raise _demo_error(
            status.HTTP_400_BAD_REQUEST,
            f"{filename} is {len(content) / 1024 / 1024:.1f}MB. This demo "
            f"accepts files up to {settings.DEMO_MAX_MB}MB.")

    if pdf_is_entirely_scanned(content):
        raise _scanned()


def pdf_is_entirely_scanned(content: bytes) -> bool:
    """Is EVERY page of this PDF without a text layer?

    It asks the ENGINE'S OWN question — `core.preprocessor.text_layer_pages`,
    whose per-page predicate is the one `_process_pdf` routes on — so the demo
    gate and the pipeline cannot disagree about what a text layer is. Nothing
    is rendered, no OCR binary runs, and no model is called.

    EVERY page, not any page. "This is a scan" is a statement about the
    document, and a document is a scan when none of it is machine-readable. The
    earlier reading (any page) refused a perfectly good digital PDF for one
    near-blank page — a trailing page holding only a logo — which an investor
    would experience as the demo breaking on a real document.

    ⚠ WHAT THAT GIVES UP, SAID PLAINLY: a MIXED document — nine scanned pages
    behind one digital cover sheet — is now accepted, and the pipeline WILL OCR
    those nine pages. So the demo's property is no longer "nothing here is ever
    OCR'd"; it is "a document that is nothing but a scan is refused, with an
    explanation, instead of being read by machine". The refusal is about not
    claiming scanned-document support, and a mixed file is a weaker claim than
    a scan, not the same one.

    A PDF with no pages at all is NOT reported as a scan — there is nothing to
    have a text layer — and fails later on its own merits.
    """
    for p in (str(_BACKEND_DIR / "engine"), str(_BACKEND_DIR),
              str(_BACKEND_DIR.parent)):
        if p not in sys.path:
            sys.path.insert(0, p)
    from core.preprocessor import text_layer_pages

    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(content)
        tmp.close()
        try:
            missing, total = text_layer_pages(tmp.name)
            return total > 0 and len(missing) == total
        except HTTPException:
            raise
        except Exception as exc:
            # A file that cannot be read as a PDF is not a scan, and saying it
            # is would send the user off to find a "digital" copy of a file
            # that is simply broken.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"This file could not be read as a PDF ({exc}).",
            )
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def enforce_upload_policy(db, user, files: Sequence[tuple[str, bytes]]) -> None:
    """The whole demo upload gate: quota first, then every file.

    A no-op for a user whose client_id is not configured as a demo tenant,
    which is the only reason it is safe to call from the shared upload path.
    """
    if not is_demo_user(user):
        return
    check_upload_quota(db, user)
    for filename, content in files:
        check_demo_file(filename, content)


# ── C — the sample documents folder ───────────────────────────────────────────

def sample_docs_dir(client_id: Optional[str]) -> Optional[Path]:
    """`backend/demo_docs/<client_id>/`, or None if this is not a demo tenant.

    The client_id is checked against the configured list BEFORE it is used as a
    path segment, so no caller can reach a directory by naming it.
    """
    if not is_demo_client(client_id):
        return None
    return _BACKEND_DIR / SAMPLE_DOCS_DIRNAME / str(client_id)


def list_sample_docs(client_id: Optional[str]) -> list[dict]:
    """The PDFs shipped for this demo tenant: name and size, sorted by name.

    A missing directory is an empty list, not an error: a demo client with no
    samples yet is an ordinary state, and an exception here would take the
    whole Extract page down with it.
    """
    folder = sample_docs_dir(client_id)
    if folder is None or not folder.is_dir():
        return []
    out = []
    for entry in sorted(folder.iterdir(), key=lambda p: p.name.lower()):
        if entry.is_file() and entry.suffix.lower() == _PDF_SUFFIX:
            out.append({"filename": entry.name,
                        "size_bytes": entry.stat().st_size})
    return out


def resolve_sample_doc(client_id: Optional[str], filename: str) -> Path:
    """A sample file by name, or 404.

    TRAVERSAL IS NOT DEFENDED AGAINST, IT IS UNREPRESENTABLE: the name must be
    one of the names `list_sample_docs` returned for this tenant, compared as a
    string. `../../etc/passwd`, an absolute path and a symlink target all fail
    the same way — they are not in the list — so there is no sanitising step to
    get subtly wrong.
    """
    folder = sample_docs_dir(client_id)
    if folder is None:
        raise HTTPException(status_code=404, detail="Not found")
    allowed = {d["filename"] for d in list_sample_docs(client_id)}
    if filename not in allowed:
        raise HTTPException(
            status_code=404,
            detail=f"No sample document named {filename!r}")
    return folder / filename
