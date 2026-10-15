# Sample documents — pearx_demo

Drop the demo PDFs for `client_id = pearx_demo` in this directory. They ship
inside the backend image and are served read-only by `GET /api/demo/sample-docs`
(see `backend/app/api/routes/demo.py`).

Rules enforced by the backend, not by this folder:

* only `.pdf` files are listed — anything else here is ignored;
* a file is downloadable and extractable only if the listing returned its name,
  so the listing is the whitelist;
* every sample goes through the same upload pipeline as a user's own file,
  including the demo's size limit and the scanned-document refusal. That
  refusal fires only when **every** page of the PDF lacks a text layer, so a
  wholly scanned sample is REFUSED at extraction time, while a mixed PDF (some
  scanned pages behind a digital one) is accepted and its scanned pages are
  read by OCR. Check them first with:

      backend\.venv\Scripts\python.exe -m scripts.check_demo_docs
