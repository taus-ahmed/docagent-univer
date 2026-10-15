"""
The investor demo: a narrower product, gated on one environment variable.

`DEMO_CLIENT_IDS` is a comma list of client_ids and is EMPTY by default, so
every test in `TestWithTheVariableUnset` is the shipped behaviour — the demo
user itself behaves exactly like any other account until someone sets it. That
class, and `TestNothingChangesForAnyoneElse`, are the proof that this feature
is invisible to the rest of the deployment; the rest of the file is what the
demo actually does.

Nothing here calls Gemini. Two tests additionally assert that the
scanned-document refusal reaches NEITHER the model NOR Tesseract, because the
point of that refusal is that it costs nothing and claims nothing.
"""
import io

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

SCANNED = ("This looks like a scanned document. Scanned-document support is "
           "in development and is not part of this demo. Please try a digital "
           "PDF.")


@pytest.fixture(autouse=True)
def _no_real_extraction(monkeypatch):
    """No background thread, no model, no OCR binary — in every test here.

    `_ocr_page` and `LLMRouter.extract` are made to RAISE rather than to
    return: a demo upload that was refused must not have reached either, and a
    stub that quietly succeeds would hide it if it had.
    """
    import threading

    class _Inert(threading.Thread):
        def start(self):
            return None

    monkeypatch.setattr("app.api.routes.extract.threading.Thread", _Inert)

    import core.preprocessor as pre

    def _no_ocr(*a, **k):
        raise AssertionError("OCR ran — the demo gate must not OCR anything")

    monkeypatch.setattr(pre, "_ocr_page", _no_ocr)

    from connectors.llm_router import LLMRouter

    def _no_llm(*a, **k):
        raise AssertionError("the model was called")

    monkeypatch.setattr(LLMRouter, "extract", _no_llm)


def _upload(client, headers, content, name="doc.pdf", mime="application/pdf",
            template_id=None, client_id="pearx_demo"):
    data = {"client_id": client_id}
    if template_id is not None:
        data["template_id"] = str(template_id)
    return client.post(
        "/api/extract/upload", headers=headers, data=data,
        files=[("files", (name, io.BytesIO(content), mime))])


def _job_count(db, user):
    from app.models.models import ExtractionJob
    return db.query(ExtractionJob).filter(
        ExtractionJob.user_id == user.id).count()


# ── B1 / B2 — what a demo account may upload ─────────────────────────────────

class TestTheDemoRefusesAScan:
    """REFUSED WHEN EVERY PAGE LACKS A TEXT LAYER — not when any page does.

    "This is a scan" is a statement about the document. The earlier reading
    refused a good digital PDF for one near-blank trailing page, which in front
    of an investor looks like the demo breaking on a real file. The cost is
    stated in `pdf_is_entirely_scanned` and tested below: a mixed file is now
    accepted and its scanned pages ARE OCR'd.
    """

    def test_a_scanned_pdf_is_refused_with_the_exact_sentence(
            self, client, demo_auth, demo_on, scanned_pdf_bytes):
        r = _upload(client, demo_auth, scanned_pdf_bytes, name="scan.pdf")
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == SCANNED

    def test_a_multi_page_scan_is_refused_too(
            self, client, demo_auth, demo_on, scanned_two_page_pdf_bytes):
        """Every page, so a two-page scan is still a scan."""
        r = _upload(client, demo_auth, scanned_two_page_pdf_bytes,
                    name="scan2.pdf")
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == SCANNED

    def test_a_mixed_pdf_is_ACCEPTED(
            self, client, demo_auth, demo_on, mixed_pdf_bytes):
        """One digital page and one scanned page: not a scanned document.

        ⚠ This is the trade, and it is deliberate: the pipeline will OCR that
        second page. The demo's claim is "we do not support scanned documents
        yet", not "nothing here is ever OCR'd".
        """
        r = _upload(client, demo_auth, mixed_pdf_bytes, name="mixed.pdf")
        assert r.status_code == 202, r.text

    def test_refusing_it_costs_no_job_row(
            self, client, demo_auth, demo_on, scanned_pdf_bytes, db, demo_user):
        before = _job_count(db, demo_user)
        _upload(client, demo_auth, scanned_pdf_bytes, name="scan.pdf")
        assert _job_count(db, demo_user) == before

    def test_an_image_gets_the_same_sentence_not_a_type_error(
            self, client, demo_auth, demo_on, png_bytes):
        """An image has no text layer at all, and "this is a photograph of a
        document" is what the sentence is about."""
        r = _upload(client, demo_auth, png_bytes, name="receipt.png",
                    mime="image/png")
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == SCANNED

    def test_a_digital_pdf_is_accepted(self, client, demo_auth, demo_on,
                                       pdf_bytes):
        r = _upload(client, demo_auth, pdf_bytes)
        assert r.status_code == 202, r.text

    def test_the_predicate_is_the_pipelines_own(
            self, scanned_pdf_bytes, mixed_pdf_bytes, pdf_bytes, tmp_path):
        """Not a second opinion about what a text layer is: the demo asks
        `core.preprocessor.text_layer_pages`, whose per-page predicate is the
        one `_process_pdf` routes on."""
        from core.preprocessor import page_needs_ocr, text_layer_pages

        scan = tmp_path / "scan.pdf"
        scan.write_bytes(scanned_pdf_bytes)
        digital = tmp_path / "digital.pdf"
        digital.write_bytes(pdf_bytes)
        mixed = tmp_path / "mixed.pdf"
        mixed.write_bytes(mixed_pdf_bytes)

        assert text_layer_pages(scan) == ([1], 1)
        assert text_layer_pages(digital) == ([], 1)
        # The denominator is what the rule turns on, so the helper reports it.
        assert text_layer_pages(mixed) == ([2], 2)
        assert page_needs_ocr("") is True
        assert page_needs_ocr("x" * 49) is True
        assert page_needs_ocr("x" * 50) is False

    def test_the_document_level_rule_is_all_not_any(
            self, scanned_pdf_bytes, mixed_pdf_bytes, pdf_bytes):
        """The one-line statement of the change, at the level it was made."""
        from app.core.demo import pdf_is_entirely_scanned

        assert pdf_is_entirely_scanned(scanned_pdf_bytes) is True
        assert pdf_is_entirely_scanned(mixed_pdf_bytes) is False
        assert pdf_is_entirely_scanned(pdf_bytes) is False


class TestTheDemosOtherLimits:
    def test_a_non_pdf_that_is_not_an_image_is_refused_as_pdf_only(
            self, client, demo_auth, demo_on):
        """`.yaml` passes the ordinary upload validator, so this is the demo's
        own rule talking, not the shared one."""
        r = _upload(client, demo_auth, b"client_id: x\n", name="schema.yaml",
                    mime="application/x-yaml")
        assert r.status_code == 400, r.text
        assert "PDF" in r.json()["detail"]

    def test_a_file_over_the_demo_ceiling_is_refused(
            self, client, demo_auth, demo_on, pdf_bytes):
        """Padded past DEMO_MAX_MB (10) with a trailing PDF comment, so the
        file is still a perfectly readable digital PDF: the size is the only
        reason it is refused, and the answer is not the scanned sentence."""
        padded = pdf_bytes + b"\n% " + b"x" * (11 * 1024 * 1024)
        r = _upload(client, demo_auth, padded, name="big.pdf")
        assert r.status_code == 400, r.text
        assert "10MB" in r.json()["detail"]
        assert r.json()["detail"] != SCANNED

    def test_the_upload_ceiling_counts_the_jobs_already_on_the_account(
            self, client, demo_auth, demo_on, pdf_bytes, db, demo_user,
            monkeypatch):
        from app.config import settings

        used = _job_count(db, demo_user)
        monkeypatch.setattr(settings, "DEMO_MAX_UPLOADS", used)
        r = _upload(client, demo_auth, pdf_bytes)
        assert r.status_code == 429, r.text
        assert str(used) in r.json()["detail"]

        monkeypatch.setattr(settings, "DEMO_MAX_UPLOADS", used + 1)
        assert _upload(client, demo_auth, pdf_bytes).status_code == 202


# ── The kill switch ───────────────────────────────────────────────────────────

class TestUploadsCanBeTurnedOff:
    """DEMO_UPLOADS_ENABLED=false closes the demo's upload door and leaves the
    sample documents open — which is the whole point: it is for a demo that has
    started going badly, not for taking the demo down."""

    @pytest.fixture
    def uploads_off(self, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "DEMO_UPLOADS_ENABLED", False)

    def test_the_demos_upload_is_refused_with_the_exact_sentence(
            self, client, demo_auth, demo_on, uploads_off, pdf_bytes):
        r = _upload(client, demo_auth, pdf_bytes)
        assert r.status_code == 403, r.text
        assert r.json()["detail"] == \
            "Uploads are disabled in this demo. Please use the sample documents."

    def test_it_is_refused_before_the_file_is_even_looked_at(
            self, client, demo_auth, demo_on, uploads_off, scanned_pdf_bytes,
            db, demo_user):
        """A scan would also be refused, with a different sentence. The door
        comes first, and nothing is read or written."""
        before = _job_count(db, demo_user)
        r = _upload(client, demo_auth, scanned_pdf_bytes, name="scan.pdf")
        assert r.status_code == 403, r.text
        assert r.json()["detail"] != SCANNED
        assert _job_count(db, demo_user) == before

    def test_the_sample_documents_still_list(
            self, client, demo_auth, demo_on, uploads_off, demo_docs):
        r = client.get("/api/demo/sample-docs", headers=demo_auth)
        assert r.status_code == 200, r.text
        assert [f["filename"] for f in r.json()["files"]] == \
            ["sample-invoice.pdf"]

    def test_a_sample_still_downloads(
            self, client, demo_auth, demo_on, uploads_off, demo_docs,
            pdf_bytes):
        r = client.get("/api/demo/sample-docs/sample-invoice.pdf/download",
                       headers=demo_auth)
        assert r.status_code == 200, r.text
        assert r.content == pdf_bytes

    def test_a_sample_still_extracts(
            self, client, demo_auth, demo_on, uploads_off, demo_docs, db,
            demo_user):
        before = _job_count(db, demo_user)
        r = client.post("/api/demo/sample-docs/sample-invoice.pdf/extract",
                        headers=demo_auth)
        assert r.status_code == 202, r.text
        assert _job_count(db, demo_user) == before + 1

    def test_the_switch_does_not_touch_anybody_else(
            self, client, auth, demo_on, uploads_off, pdf_bytes):
        r = _upload(client, auth["acme2"], pdf_bytes, client_id="acme_001")
        assert r.status_code == 202, r.text

    def test_it_does_not_touch_a_demo_user_while_it_is_on(
            self, client, demo_auth, demo_on, pdf_bytes):
        """The default is true, so this is the shipped behaviour."""
        from app.config import settings
        assert settings.DEMO_UPLOADS_ENABLED is True
        assert _upload(client, demo_auth, pdf_bytes).status_code == 202

    def test_with_the_variable_unset_the_switch_is_inert(
            self, client, demo_auth, uploads_off, pdf_bytes):
        """No `demo_on`: not a demo tenant, so the switch means nothing."""
        assert _upload(client, demo_auth, pdf_bytes).status_code == 202


class TestADeliberateRefusalIsMarkedAsOne:
    """The Extract page replaces raw error text with a neutral sentence for
    demo users (`frontend/lib/demo-error.ts`). The sentences the demo WROTE
    must survive that, so the backend tags them — otherwise an investor reads
    "Something went wrong" where we had written a real explanation."""

    HEADER = "x-demo-notice"

    def test_the_scanned_refusal_is_tagged(
            self, client, demo_auth, demo_on, scanned_pdf_bytes):
        r = _upload(client, demo_auth, scanned_pdf_bytes, name="scan.pdf")
        assert r.headers.get(self.HEADER) == "1", dict(r.headers)

    def test_the_uploads_disabled_refusal_is_tagged(
            self, client, demo_auth, demo_on, pdf_bytes, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "DEMO_UPLOADS_ENABLED", False)
        r = _upload(client, demo_auth, pdf_bytes)
        assert r.headers.get(self.HEADER) == "1", dict(r.headers)

    def test_the_quota_refusal_is_tagged(
            self, client, demo_auth, demo_on, pdf_bytes, db, demo_user,
            monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "DEMO_MAX_UPLOADS",
                            _job_count(db, demo_user))
        r = _upload(client, demo_auth, pdf_bytes)
        assert r.headers.get(self.HEADER) == "1", dict(r.headers)

    def test_the_pdf_only_refusal_is_tagged(self, client, demo_auth, demo_on):
        r = _upload(client, demo_auth, b"client_id: x\n", name="s.yaml",
                    mime="application/x-yaml")
        assert r.headers.get(self.HEADER) == "1", dict(r.headers)

    def test_an_ordinary_error_is_NOT_tagged(
            self, client, demo_auth, demo_on, pdf_bytes, templates):
        """A 403 about somebody else's template is not a demo message, and the
        demo user should see the neutral sentence for it, not this."""
        r = _upload(client, demo_auth, pdf_bytes,
                    template_id=templates["other_private"].id)
        assert r.status_code == 403
        assert self.HEADER not in {k.lower() for k in r.headers}

    def test_nothing_is_tagged_for_a_normal_user(
            self, client, auth, demo_on, png_bytes):
        r = _upload(client, auth["acme2"], png_bytes, name="r.png",
                    mime="image/png", client_id="acme_001")
        assert r.status_code == 202
        assert self.HEADER not in {k.lower() for k in r.headers}


# ── B3 — the template picker ──────────────────────────────────────────────────

class TestTheDemoSeesNoSystemDefaults:
    def test_a_default_it_does_not_own_is_not_in_the_list(
            self, client, demo_auth, demo_on, templates, demo_templates):
        r = client.get("/api/templates", headers=demo_auth)
        assert r.status_code == 200, r.text
        names = {t["name"] for t in r.json()}
        assert "system_default" not in names
        # ...but its own templates are all there, including one that happens to
        # carry is_default itself: the rule is about ownership, not the flag.
        assert {"demo_private", "demo_owned_default"} <= names

    def test_fetching_that_default_by_id_is_refused(
            self, client, demo_auth, demo_on, templates):
        r = client.get(f"/api/templates/{templates['system_default'].id}",
                       headers=demo_auth)
        assert r.status_code == 403, r.text

    def test_extracting_with_that_default_is_refused(
            self, client, demo_auth, demo_on, templates, pdf_bytes):
        r = _upload(client, demo_auth, pdf_bytes,
                    template_id=templates["system_default"].id)
        assert r.status_code == 403, r.text

    def test_extracting_with_its_own_template_still_works(
            self, client, demo_auth, demo_on, demo_templates, pdf_bytes):
        r = _upload(client, demo_auth, pdf_bytes,
                    template_id=demo_templates["demo_private"].id)
        assert r.status_code == 202, r.text


# ── B4 — the banner's one bit ─────────────────────────────────────────────────

class TestIsDemoReachesTheFrontend:
    def test_the_demo_user_is_told_they_are_a_demo(self, client, demo_auth,
                                                   demo_on):
        r = client.get("/api/auth/me", headers=demo_auth)
        assert r.status_code == 200, r.text
        assert r.json()["is_demo"] is True

    def test_everyone_else_is_told_they_are_not(self, client, auth, demo_on):
        for name in ("super", "acme", "acme2", "other"):
            r = client.get("/api/auth/me", headers=auth[name])
            assert r.json()["is_demo"] is False, name

    def test_with_the_variable_unset_even_the_demo_user_is_not(
            self, client, demo_auth):
        assert client.get("/api/auth/me",
                          headers=demo_auth).json()["is_demo"] is False


# ── C — the sample documents folder ──────────────────────────────────────────

class TestSampleDocuments:
    def test_the_listing_offers_the_pdfs_and_nothing_else(
            self, client, demo_auth, demo_on, demo_docs):
        r = client.get("/api/demo/sample-docs", headers=demo_auth)
        assert r.status_code == 200, r.text
        names = [f["filename"] for f in r.json()["files"]]
        assert names == ["sample-invoice.pdf"], names
        assert r.json()["files"][0]["size_bytes"] > 0

    def test_a_sample_downloads_byte_for_byte(
            self, client, demo_auth, demo_on, demo_docs, pdf_bytes):
        r = client.get("/api/demo/sample-docs/sample-invoice.pdf/download",
                       headers=demo_auth)
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert r.content == pdf_bytes

    @pytest.mark.parametrize("name", [
        "notes.txt",                      # in the folder, not in the listing
        "../../app/main.py",
        "..%2F..%2Fapp%2Fmain.py",
        "/etc/passwd",
        "sample-invoice.pdf.bak",
        "SAMPLE-INVOICE.PDF",             # the listing is exact, not casefolded
    ])
    def test_only_a_name_the_listing_returned_is_served(
            self, client, demo_auth, demo_on, demo_docs, name):
        r = client.get(f"/api/demo/sample-docs/{name}/download",
                       headers=demo_auth)
        assert r.status_code == 404, (name, r.status_code)

    def test_using_a_sample_starts_a_real_job_for_this_user(
            self, client, demo_auth, demo_on, demo_docs, db, demo_user):
        from app.models.models import ExtractionJob

        before = _job_count(db, demo_user)
        r = client.post("/api/demo/sample-docs/sample-invoice.pdf/extract",
                        headers=demo_auth)
        assert r.status_code == 202, r.text
        assert _job_count(db, demo_user) == before + 1
        job = db.query(ExtractionJob).filter(
            ExtractionJob.id == r.json()["job_id"]).first()
        # The tenant comes from the token even though this route takes no
        # client_id at all.
        assert job.client_id == "pearx_demo"
        assert job.user_id == demo_user.id

    def test_a_sample_goes_through_the_same_demo_gate(
            self, client, demo_auth, demo_on, demo_docs, scanned_pdf_bytes):
        """The whole reason "use this sample" calls `_start_extraction_job`:
        a scanned sample is refused with the same sentence, not waved through
        because it came from us."""
        (demo_docs / "scanned-sample.pdf").write_bytes(scanned_pdf_bytes)
        r = client.post("/api/demo/sample-docs/scanned-sample.pdf/extract",
                        headers=demo_auth)
        assert r.status_code == 422, r.text
        assert r.json()["detail"] == SCANNED

    def test_a_sample_respects_the_upload_ceiling_too(
            self, client, demo_auth, demo_on, demo_docs, db, demo_user,
            monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "DEMO_MAX_UPLOADS",
                            _job_count(db, demo_user))
        r = client.post("/api/demo/sample-docs/sample-invoice.pdf/extract",
                        headers=demo_auth)
        assert r.status_code == 429, r.text


class TestTheFolderIsInvisibleToEveryoneElse:
    @pytest.mark.parametrize("path", [
        "/api/demo/sample-docs",
        "/api/demo/sample-docs/sample-invoice.pdf/download",
    ])
    def test_a_normal_user_gets_404_not_403(
            self, client, auth, demo_on, demo_docs, path):
        for name in ("super", "acme", "acme2", "other"):
            r = client.get(path, headers=auth[name])
            assert r.status_code == 404, (name, path, r.status_code)

    def test_a_normal_user_cannot_extract_a_sample_either(
            self, client, auth, demo_on, demo_docs):
        r = client.post("/api/demo/sample-docs/sample-invoice.pdf/extract",
                        headers=auth["acme2"])
        assert r.status_code == 404, r.text

    def test_the_endpoints_need_a_token_at_all(self, client, demo_on, demo_docs):
        assert client.get("/api/demo/sample-docs").status_code in (401, 403)

    def test_with_the_variable_unset_there_is_no_folder_for_anyone(
            self, client, demo_auth, demo_docs):
        """No `demo_on`: the shipped default. Even the demo user gets 404."""
        assert client.get("/api/demo/sample-docs",
                          headers=demo_auth).status_code == 404


# ── D — proof that nothing changed for anyone else ───────────────────────────

class TestNothingChangesForAnyoneElse:
    """Every rule above is gated on the tenant, so a non-demo user must be
    unable to tell the feature was added — even while it is switched ON."""

    def test_a_normal_user_may_still_upload_an_image(
            self, client, auth, demo_on, png_bytes):
        r = _upload(client, auth["acme2"], png_bytes, name="receipt.png",
                    mime="image/png", client_id="acme_001")
        assert r.status_code == 202, r.text

    def test_a_normal_user_may_still_upload_a_scan(
            self, client, auth, demo_on, scanned_pdf_bytes):
        """The scanned-document refusal is a DEMO rule. The product OCRs."""
        r = _upload(client, auth["acme2"], scanned_pdf_bytes, name="scan.pdf",
                    client_id="acme_001")
        assert r.status_code == 202, r.text

    def test_a_normal_user_may_still_upload_a_mixed_pdf(
            self, client, auth, demo_on, mixed_pdf_bytes):
        r = _upload(client, auth["acme2"], mixed_pdf_bytes, name="mixed.pdf",
                    client_id="acme_001")
        assert r.status_code == 202, r.text

    def test_a_normal_user_may_still_upload_a_large_file(
            self, client, auth, demo_on, pdf_bytes):
        """Over the demo's 10MB, under the product's 50MB."""
        padded = pdf_bytes + b"\n% " + b"x" * (11 * 1024 * 1024)
        r = _upload(client, auth["acme2"], padded, name="big.pdf",
                    client_id="acme_001")
        assert r.status_code == 202, r.text

    def test_a_normal_user_still_sees_system_default_templates(
            self, client, auth, demo_on, templates):
        names = {t["name"] for t in
                 client.get("/api/templates", headers=auth["acme2"]).json()}
        assert "system_default" in names

    def test_a_normal_user_may_still_extract_with_a_system_default(
            self, client, auth, demo_on, templates, pdf_bytes):
        r = _upload(client, auth["acme2"], pdf_bytes, client_id="acme_001",
                    template_id=templates["system_default"].id)
        assert r.status_code == 202, r.text

    @pytest.mark.parametrize("path", ["/api/templates", "/api/schemas",
                                      "/api/jobs", "/api/auth/me"])
    @pytest.mark.parametrize("who", ["super", "acme", "acme2", "other"])
    def test_the_same_request_gives_the_same_answer_either_way(
            self, client, auth, monkeypatch, path, who):
        """Read it with the variable unset, then with the demo switched on, and
        compare the responses. This is the strongest form of "no behaviour
        change" available: not an argument about the gate, a diff."""
        from app.config import settings

        monkeypatch.setattr(settings, "DEMO_CLIENT_IDS", "")
        off = client.get(path, headers=auth[who])
        monkeypatch.setattr(settings, "DEMO_CLIENT_IDS", "pearx_demo")
        on = client.get(path, headers=auth[who])
        assert off.status_code == on.status_code
        assert off.json() == on.json(), (path, who)


class TestWithTheVariableUnset:
    """The shipped default is empty, and empty must mean OFF — including for
    the account that will one day be the demo."""

    def test_the_demo_user_may_upload_an_image(self, client, demo_auth,
                                               png_bytes):
        r = _upload(client, demo_auth, png_bytes, name="receipt.png",
                    mime="image/png")
        assert r.status_code == 202, r.text

    def test_the_demo_user_may_upload_a_scan(self, client, demo_auth,
                                             scanned_pdf_bytes):
        r = _upload(client, demo_auth, scanned_pdf_bytes, name="scan.pdf")
        assert r.status_code == 202, r.text

    def test_the_demo_user_sees_system_defaults(self, client, demo_auth,
                                                templates):
        names = {t["name"] for t in
                 client.get("/api/templates", headers=demo_auth).json()}
        assert "system_default" in names

    def test_nobody_is_a_demo_user(self, demo_user, users):
        from app.core.demo import demo_client_ids, is_demo_user
        assert demo_client_ids() == frozenset()
        assert is_demo_user(demo_user) is False
        for u in users.values():
            assert is_demo_user(u) is False

    def test_an_untenanted_super_admin_is_never_a_demo_user(self, monkeypatch,
                                                            users):
        """`client_id=None` must not match an empty-string entry or a stray
        comma in the variable."""
        from app.config import settings
        from app.core.demo import is_demo_user
        monkeypatch.setattr(settings, "DEMO_CLIENT_IDS", "pearx_demo, ,")
        assert is_demo_user(users["super"]) is False
