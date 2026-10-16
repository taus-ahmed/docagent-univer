"""
DocAgent — demo routes: the sample documents a demo account can extract.

THE FOLDER IS THE WHITELIST. PDFs ship in the image at
`backend/demo_docs/<client_id>/`, the listing endpoint is the only thing that
turns a name into a file, and download and extract accept only a name that
listing returned. Traversal is therefore not filtered, it is unrepresentable
(`core/demo.py::resolve_sample_doc`), and no request ever writes there.

EVERY ROUTE HERE IS 404 FOR A NON-DEMO USER — not 403. A user who is not part
of the demo should not be able to tell these endpoints exist, and 404 is also
the honest answer: with `DEMO_CLIENT_IDS` unset, which is the default, there is
no demo tenant and no folder for anyone.

"Use this document" does NOT re-implement extraction. It hands the file's bytes
to `extract.py::_start_extraction_job`, the same function the upload endpoint
calls, as the signed-in user — so the demo's own limits (PDF only, size, quota,
scanned-document refusal) apply to a sample document exactly as they do to an
upload, and a sample document cannot become a way around them.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.demo import is_demo_user, list_sample_docs, resolve_sample_doc
from app.core.storage import get_storage
from app.models import get_db, User
from app.schemas.schemas import ExtractUploadResponse

router = APIRouter(prefix="/api/demo", tags=["demo"])


def _demo_only(current_user: User) -> None:
    if not is_demo_user(current_user):
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/sample-docs")
def list_demo_documents(current_user: User = Depends(get_current_user)):
    """The sample documents shipped for this demo tenant.

    The names in this response are the ONLY names the two endpoints below
    accept, which is what makes them safe.
    """
    _demo_only(current_user)
    return {"files": list_sample_docs(current_user.client_id)}


@router.get("/sample-docs/{filename}/download")
def download_demo_document(filename: str,
                           current_user: User = Depends(get_current_user)):
    """Hand back one sample document as a file."""
    _demo_only(current_user)
    path = resolve_sample_doc(current_user.client_id, filename)
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@router.post("/sample-docs/{filename}/extract", response_model=ExtractUploadResponse,
             status_code=202)
async def extract_demo_document(
    filename: str,
    template_id: Optional[int] = Form(None),
    options: Optional[str] = Form(None),
    selected_pages: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage=Depends(get_storage),
):
    """Run the ordinary extraction pipeline on one sample document.

    No `client_id` parameter: the tenant comes from the token
    (`resolve_client_id`), which for a demo user is the demo client by
    definition. Passing one would only create something to disagree with.
    """
    _demo_only(current_user)
    path = resolve_sample_doc(current_user.client_id, filename)

    from app.api.routes.extract import _IncomingUpload, _start_extraction_job
    from app.core import demo_audit

    return await _start_extraction_job(
        [_IncomingUpload.from_path(path)],
        audit_event=demo_audit.SAMPLE_EXTRACT,
        requested_client_id=None,
        template_id=template_id,
        options=options,
        selected_pages=selected_pages,
        db=db,
        current_user=current_user,
        storage=storage,
    )
