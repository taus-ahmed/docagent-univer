"""Password-protected PDFs (Part 1.7).

A PDF encrypted with a USER password cannot be read without it; one with
only an OWNER password (permissions) opens with the empty password, as it
always did. The password is supplied with the upload and lives only in
memory: it is never written to disk, stored, logged or returned. The worker
decrypts the file into a temp copy (same handling as every temp copy —
random name, released when the file is done) and reads that.

    pdf_lock_state(source) -> "open" | "needs_password"
    decrypt_to(source, password, dest) -> "ok" | PASSWORD_REQUIRED | PASSWORD_INCORRECT
"""
from __future__ import annotations

PASSWORD_REQUIRED = "password_required"
PASSWORD_INCORRECT = "password_incorrect"

MESSAGES = {
    PASSWORD_REQUIRED: ("This PDF is password-protected: password required. "
                        "Upload it again with its password (the password is "
                        "used once and never saved)."),
    PASSWORD_INCORRECT: ("This PDF is password-protected: password incorrect. "
                         "Upload it again with the right password (the "
                         "password is used once and never saved)."),
}


def _reader(source):
    import io
    from pypdf import PdfReader
    if isinstance(source, (bytes, bytearray)):
        return PdfReader(io.BytesIO(source), strict=False)
    return PdfReader(str(source), strict=False)


def pdf_lock_state(source) -> str:
    """"open" (not encrypted, or owner-password only) or "needs_password"."""
    r = _reader(source)
    if not r.is_encrypted:
        return "open"
    try:
        return "open" if r.decrypt("") else "needs_password"
    except Exception:
        return "needs_password"


def page_count_or_none(source, password=None):
    """Pages, decrypting with `password` in memory when needed; None when
    the file cannot be opened with what was given."""
    r = _reader(source)
    try:
        if r.is_encrypted and not (r.decrypt("") or (password and r.decrypt(password))):
            return None
        return len(r.pages)
    except Exception:
        return None


def decrypt_to(source, password, dest) -> str:
    """Write a decrypted copy of `source` to `dest`. Never raises with the
    password in the message."""
    if not password:
        return PASSWORD_REQUIRED
    r = _reader(source)
    try:
        ok = r.decrypt(password)
    except Exception:
        ok = 0
    if not ok:
        return PASSWORD_INCORRECT
    from pypdf import PdfWriter
    w = PdfWriter(clone_from=r)
    with open(dest, "wb") as fh:
        w.write(fh)
    return "ok"


__all__ = ["MESSAGES", "PASSWORD_INCORRECT", "PASSWORD_REQUIRED", "decrypt_to",
           "page_count_or_none", "pdf_lock_state"]
