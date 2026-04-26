"""
DocAgent v2 — Google Drive Routes
GET  /api/drive/auth/status   — check auth state
POST /api/drive/auth          — initiate OAuth flow
GET  /api/drive/folders/{id}  — list folder contents
POST /api/drive/extract       — extract from Drive folder
GET  /api/watch               — list watch folders
POST /api/watch               — add watch folder
DELETE /api/watch/{id}        — remove watch folder
POST /api/watch/check         — manually trigger a watch check
"""

import sys
import tempfile
import shutil
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.storage import get_storage
from app.models import get_db, User, ExtractionJob, WatchFolder
from app.schemas.schemas import (
    DriveAuthStatus, DriveFolderContents, DriveFolder as DriveFolderSchema,
    DriveFile as DriveFileSchema, WatchFolderCreate, WatchFolderResponse,
    ExtractUploadResponse,
)

router = APIRouter(prefix="/api", tags=["drive"])


def _get_drive():
    """Load the Google Drive connector from the engine."""
    backend_dir = Path(__file__).resolve().parent.parent.parent.parent
    engine_dir = backend_dir / "engine"
    for p in [str(backend_dir), str(engine_dir)]:
        if p not in sys.path:
            sys.path.insert(0, p)
    from gdrive import get_drive_connector
    return get_drive_connector()


# ─── Auth ─────────────────────────────────────────────────────────────────────

@router.get("/drive/auth/status", response_model=DriveAuthStatus)
def drive_auth_status(_: User = Depends(get_current_user)):
    """Check Google Drive authentication status."""
    try:
        drive = _get_drive()
        return DriveAuthStatus(
            is_configured=drive.is_configured,
            is_authenticated=drive.is_authenticated,
        )
    except Exception as e:
        return DriveAuthStatus(is_configured=False, is_authenticated=False)


@router.post("/drive/auth")
def drive_auth(current_user: User = Depends(get_current_user)):
    """
    Initiate Google Drive OAuth flow.
    Returns instructions — user must complete OAuth in browser.
    """
    try:
        drive = _get_drive()
        if not drive.is_configured:
            raise HTTPException(
                status_code=400,
                detail="credentials.json not found. Please add Google OAuth credentials to the server.",
            )
        success = drive.authenticate()
        if success:
            return {"message": "Google Drive authenticated successfully", "authenticated": True}
        else:
            raise HTTPException(status_code=500, detail="Authentication failed. Check server logs.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Folder Browser ───────────────────────────────────────────────────────────

@router.get("/drive/folders/{folder_id}", response_model=DriveFolderContents)
def list_drive_folder(
    folder_id: str = "root",
    current_user: User = Depends(get_current_user),
):
    """List files and subfolders in a Drive folder."""
    try:
        drive = _get_drive()

        if not drive.is_authenticated:
            raise HTTPException(status_code=401, detail="Google Drive not authenticated")

        folders = drive.list_folders(folder_id)
        files = drive.list_files(folder_id)

        return DriveFolderContents(
            folders=[DriveFolderSchema(id=f.id, name=f.name) for f in folders],
            files=[
                DriveFileSchema(
                    id=f.id, name=f.name, mime_type=f.mime_type,
                    size=f.size, modified_time=f.modified_time,
                    is_supported=f.is_supported,
                )
                for f in files
            ],
            total_files=len(files),
            supported_files=sum(1 for f in files if f.is_supported),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Drive Extraction ─────────────────────────────────────────────────────────

@router.post("/drive/extract", response_model=ExtractUploadResponse, status_code=202)
def extract_from_drive(
    folder_id: str,
    client_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage=Depends(get_storage),
):
    """Download files from a Drive folder and run extraction."""
    drive = _get_drive()
    if not drive.is_authenticated:
        raise HTTPException(status_code=401, detail="Google Drive not authenticated")

    schema_path = storage.get_schema_path(client_id)
    if not schema_path:
        raise HTTPException(status_code=404, detail=f"Schema not found for client '{client_id}'")

    files = drive.list_files(folder_id)
    supported = [f for f in files if f.is_supported]

    if not supported:
        raise HTTPException(status_code=400, detail="No supported files in folder")

    job = ExtractionJob(
        user_id=current_user.id,
        client_id=client_id,
        status="pending",
        total_docs=len(supported),
        input_source="drive",
        input_folder=folder_id,
        started_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    background_tasks.add_task(
        _run_drive_extraction, job.id, folder_id, supported, str(schema_path), str(db.bind.url)
    )

    return ExtractUploadResponse(
        job_id=job.id,
        message=f"Drive extraction started for {len(supported)} file(s)",
        total_files=len(supported),
        status="processing",
    )


def _run_drive_extraction(job_id, folder_id, drive_files, schema_path, db_url):
    """Background task: download Drive files then run extraction."""
    import json, time
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.models import ExtractionJob, DocumentResult, Base

    engine = create_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})
    Session = sessionmaker(bind=engine)
    session = Session()

    temp_dir = Path(tempfile.mkdtemp(prefix="docagent_drive_"))
    try:
        drive = _get_drive()
        downloaded = []
        for f in drive_files:
            path = drive.download_file(f.id, f.name, temp_dir)
            if path:
                downloaded.append(path)

        from app.api.routes.extract import _run_extraction_sync
        _run_extraction_sync(job_id, downloaded, schema_path, db_url)

    except Exception as e:
        try:
            job = session.query(ExtractionJob).filter_by(id=job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.completed_at = datetime.utcnow()
                session.commit()
        except Exception as inner_e:
            import logging
            logging.getLogger("docagent.drive").error(f"[drive job {job_id}] DB error status write failed: {inner_e}")
    finally:
        session.close()
        shutil.rmtree(temp_dir, ignore_errors=True)


# ─── Watch Folders ────────────────────────────────────────────────────────────

@router.get("/watch", response_model=list[WatchFolderResponse])
def list_watch_folders(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List watch folders for current user."""
    q = db.query(WatchFolder).filter(WatchFolder.is_active == True)
    if current_user.role != "admin":
        q = q.filter(WatchFolder.user_id == current_user.id)
    return q.order_by(WatchFolder.created_at.desc()).all()


@router.post("/watch", response_model=WatchFolderResponse, status_code=201)
def add_watch_folder(
    payload: WatchFolderCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    storage=Depends(get_storage),
):
    """Add a new watch folder."""
    # Verify schema exists
    schema_path = storage.get_schema_path(payload.client_id)
    if not schema_path:
        raise HTTPException(status_code=404, detail=f"Schema not found for client '{payload.client_id}'")

    # Check not already watching
    existing = db.query(WatchFolder).filter(
        WatchFolder.folder_id == payload.folder_id,
        WatchFolder.user_id == current_user.id,
        WatchFolder.is_active == True,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Already watching this folder")

    wf = WatchFolder(
        user_id=current_user.id,
        folder_id=payload.folder_id,
        folder_name=payload.folder_name,
        folder_path=payload.folder_path,
        client_id=payload.client_id,
        auto_upload_results=payload.auto_upload_results,
        poll_interval_minutes=payload.poll_interval_minutes,
    )
    db.add(wf)
    db.commit()
    db.refresh(wf)
    return wf


@router.delete("/watch/{watch_id}")
def remove_watch_folder(
    watch_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Stop watching a folder."""
    wf = db.query(WatchFolder).filter(WatchFolder.id == watch_id).first()
    if not wf:
        raise HTTPException(status_code=404, detail="Watch folder not found")
    if wf.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied")

    wf.is_active = False
    db.commit()
    return {"message": "Watch folder removed", "id": watch_id}


@router.post("/watch/check")
def manual_watch_check(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Manually trigger a watch folder check."""
    background_tasks.add_task(_do_watch_check, current_user.id, str(db.bind.url))
    return {"message": "Watch check started"}


def _do_watch_check(user_id, db_url):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.models import WatchFolder

    engine = create_engine(db_url, connect_args={"check_same_thread": False} if "sqlite" in db_url else {})
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        backend_dir = Path(__file__).resolve().parent.parent.parent.parent
        sys.path.insert(0, str(backend_dir))
        from drive_watcher import check_watched_folders

        class FakeDB:
            """Adapter between v2 models and legacy watcher."""
            def get_watch_folders(self):
                wfs = session.query(WatchFolder).filter_by(is_active=True, user_id=user_id).all()
                return [{"id": w.id, "folder_id": w.folder_id, "folder_name": w.folder_name,
                         "client_id": w.client_id, "processed_file_ids": w.get_processed_ids()} for w in wfs]

            def update_watch_folder(self, wid, processed_ids, file_count):
                wf = session.query(WatchFolder).filter_by(id=wid).first()
                if wf:
                    wf.set_processed_ids(processed_ids)
                    wf.last_file_count = file_count
                    wf.last_checked = datetime.utcnow()
                    session.commit()

        check_watched_folders(FakeDB(), verbose=False)
    except Exception as e:
        import logging
        logging.getLogger("docagent.drive").error(f"Watch check error: {e}")
    finally:
        session.close()
