"""engine/pdf_password.py — helper for Part 1.7 (not yet wired to the upload)."""
import io

from tests.harness import bootstrap as bs

bs.bootstrap()

from pdf_password import (PASSWORD_INCORRECT, PASSWORD_REQUIRED, decrypt_to,  # noqa: E402
                          page_count_or_none, pdf_lock_state)


def _pdf(user=None, owner=None):
    from pypdf import PdfWriter
    w = PdfWriter()
    w.add_blank_page(200, 200)
    if user is not None or owner is not None:
        w.encrypt(user_password=user or "", owner_password=owner or "owner-only")
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_states_and_decryption(tmp_path):
    assert pdf_lock_state(_pdf()) == "open"
    assert pdf_lock_state(_pdf(owner="o")) == "open"          # owner-only opens
    locked = _pdf(user="QZXPW-secret")
    assert pdf_lock_state(locked) == "needs_password"
    assert page_count_or_none(locked) is None
    assert page_count_or_none(locked, "QZXPW-secret") == 1
    dest = tmp_path / "d.pdf"
    assert decrypt_to(locked, None, dest) == PASSWORD_REQUIRED
    assert decrypt_to(locked, "wrong", dest) == PASSWORD_INCORRECT
    assert decrypt_to(locked, "QZXPW-secret", dest) == "ok"
    assert pdf_lock_state(dest.read_bytes()) == "open"
    assert b"QZXPW" not in dest.read_bytes()
