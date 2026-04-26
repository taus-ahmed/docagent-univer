"""
DocAgent v2 — Storage Service
Abstraction over local filesystem and S3/R2 object storage.
Phase 1: local only. Phase 3: enable S3 by setting STORAGE_BACKEND=s3.
"""

import io
import shutil
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, BinaryIO

from app.config import settings

ALLOWED_EXTENSIONS = {
    "pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp", "heic", "yml", "yaml"
}


class StorageService:
    """Unified file storage — local or S3."""

    def __init__(self):
        settings.ensure_storage_dirs()
        self._backend = settings.STORAGE_BACKEND

    # ─── Public API ───────────────────────────────────────────────────────────

    def save_upload(
        self,
        file_data: bytes | BinaryIO,
        filename: str,
        job_id: int,
        user_id: Optional[int] = None,
    ) -> tuple[str, str]:
        """
        Save an uploaded file.
        Returns (local_path_str, s3_key_or_local_key).
        """
        safe_name = self._sanitize_filename(filename)
        key = f"uploads/{user_id or 'anon'}/{job_id}/{safe_name}"

        if self._backend == "s3":
            return self._s3_put(file_data, key), key
        else:
            local_path = settings.LOCAL_UPLOAD_DIR / str(job_id) / safe_name
            local_path.parent.mkdir(parents=True, exist_ok=True)
            data = file_data if isinstance(file_data, bytes) else file_data.read()
            local_path.write_bytes(data)
            return str(local_path), key

    def save_output(
        self,
        file_data: bytes,
        filename: str,
        job_id: int,
        user_id: Optional[int] = None,
    ) -> tuple[str, str]:
        """Save an output Excel file."""
        key = f"outputs/{user_id or 'anon'}/{job_id}/{filename}"

        if self._backend == "s3":
            return self._s3_put(file_data, key), key
        else:
            local_path = settings.LOCAL_OUTPUT_DIR / str(job_id) / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_bytes(file_data)
            return str(local_path), key

    def save_schema(self, yaml_content: str, client_id: str) -> tuple[str, str]:
        """Save a YAML schema file."""
        filename = f"{client_id}.yaml"
        key = f"schemas/clients/{filename}"

        if self._backend == "s3":
            return self._s3_put(yaml_content.encode(), key), key
        else:
            local_path = settings.LOCAL_SCHEMAS_DIR / "clients" / filename
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text(yaml_content, encoding="utf-8")
            return str(local_path), key

    def get_local_path(self, key: str) -> Optional[Path]:
        """
        Get local path for a file key.
        For S3 backend, downloads to a temp location.
        """
        if self._backend == "s3":
            return self._s3_download_temp(key)
        else:
            # Key is relative; resolve relative to storage root
            if key.startswith("uploads/"):
                return settings.LOCAL_UPLOAD_DIR.parent / key
            elif key.startswith("outputs/"):
                return settings.LOCAL_OUTPUT_DIR.parent / key
            elif key.startswith("schemas/"):
                return settings.LOCAL_SCHEMAS_DIR.parent / key
            # Fallback: treat as absolute path
            p = Path(key)
            return p if p.exists() else None

    def get_schema_path(self, client_id: str) -> Optional[Path]:
        """Get local path to a client YAML schema."""
        candidates = [
            settings.LOCAL_SCHEMAS_DIR / "clients" / f"{client_id}.yaml",
            settings.LOCAL_SCHEMAS_DIR / "clients" / f"{client_id}.yml",
        ]
        for p in candidates:
            if p.exists():
                return p
        return None

    def get_job_upload_dir(self, job_id: int) -> Path:
        """Get or create the upload directory for a job."""
        d = settings.LOCAL_UPLOAD_DIR / str(job_id)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def get_output_bytes(self, path_or_key: str) -> Optional[bytes]:
        """Read output file as bytes (for download streaming)."""
        if self._backend == "s3":
            return self._s3_get(path_or_key)
        else:
            p = Path(path_or_key)
            if p.exists():
                return p.read_bytes()
            return None

    def cleanup_job(self, job_id: int):
        """Delete all files for a job (uploads only, keep outputs)."""
        upload_dir = settings.LOCAL_UPLOAD_DIR / str(job_id)
        if upload_dir.exists():
            shutil.rmtree(upload_dir, ignore_errors=True)

    def validate_upload(self, filename: str, size: int) -> Optional[str]:
        """Validate file before saving. Returns error message or None."""
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in ALLOWED_EXTENSIONS:
            return f"File type .{ext} not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        if size > settings.max_upload_bytes:
            return f"File too large ({size / 1024 / 1024:.1f}MB). Max: {settings.MAX_UPLOAD_SIZE_MB}MB"
        return None

    # ─── S3 Internals ─────────────────────────────────────────────────────────

    def _get_s3_client(self):
        import boto3
        kwargs = {
            "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
            "region_name": settings.AWS_REGION,
        }
        if settings.S3_ENDPOINT_URL:
            kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        return boto3.client("s3", **kwargs)

    def _s3_put(self, data: bytes, key: str) -> str:
        client = self._get_s3_client()
        client.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=data)
        return key

    def _s3_get(self, key: str) -> Optional[bytes]:
        try:
            client = self._get_s3_client()
            response = client.get_object(Bucket=settings.S3_BUCKET, Key=key)
            return response["Body"].read()
        except Exception:
            return None

    def _s3_download_temp(self, key: str) -> Optional[Path]:
        """Download S3 file to /tmp for local processing."""
        import tempfile
        data = self._s3_get(key)
        if data is None:
            return None
        suffix = Path(key).suffix
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        tmp.write(data)
        tmp.close()
        return Path(tmp.name)

    @staticmethod
    def _sanitize_filename(filename: str) -> str:
        """Make filename safe for storage."""
        name = Path(filename).name
        # Replace problematic chars
        for ch in [" ", "&", "?", "#", "%", "+", "=", "<", ">", "|", '"', "'"]:
            name = name.replace(ch, "_")
        return name


# Singleton
_storage = None

def get_storage() -> StorageService:
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage
