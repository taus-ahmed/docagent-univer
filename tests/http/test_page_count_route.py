"""POST /api/extract/page-count — the page-selection dialog's question.

Deleted in a 'cleanup' (6dceab5) while the extract page still called it: the
call 404ed, the page swallowed the error, and the "choose pages" dialog for a
multi-page PDF never appeared again. Found by the Part A7 browser test."""
import io


def _pdf(pages):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(200, 200)
    b = io.BytesIO()
    w.write(b)
    return b.getvalue()


def test_page_count_answers_per_file(client, auth):
    r = client.post("/api/extract/page-count", headers=auth["acme2"],
                    files=[("files", ("a.pdf", _pdf(3), "application/pdf")),
                           ("files", ("b.pdf", _pdf(1), "application/pdf"))])
    assert r.status_code == 200, r.text
    assert [x["page_count"] for x in r.json()] == [3, 1]


def test_page_count_needs_a_signed_in_user(client):
    r = client.post("/api/extract/page-count",
                    files=[("files", ("a.pdf", _pdf(1), "application/pdf"))])
    assert r.status_code in (401, 403)          # no token: refused
