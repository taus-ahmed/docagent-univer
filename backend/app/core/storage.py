"""
DocAgent — Storage Service

One key namespace, two backends. A file is identified by a KEY, and the key is
the same string whichever backend holds it:

    clients/{client_id}/jobs/{job_id}/source/{filename}    an uploaded document
    clients/{client_id}/jobs/{job_id}/output/{filename}    a generated file
    schemas/clients/{client_id}.yaml                       a client's YAML schema

Local backend puts the key under `LOCAL_STORAGE_ROOT` verbatim, so the path and
the key are the same thing. That is deliberate: they used to diverge — an
upload was WRITTEN to `storage/uploads/{job}/{name}` and its key recorded as
`uploads/{user}/{job}/{name}` — so `get_local_path(key)` pointed at a file that
had never existed there, and only the fact that callers passed the path around
directly kept it working.

TENANCY. `client_id` is the first path segment for everything a tenant owns, so
one tenant's prefix cannot contain another's, and a scoped bucket credential or
IAM prefix condition can enforce later what the code enforces now.

TRAVERSAL. Every key is built here and validated by `_safe_key`, which rejects
`..`, absolute paths, drive letters, backslashes, and empty segments. Nothing
takes a caller-supplied path: the old `get_local_path` ended in
`p = Path(key); return p if p.exists() else None`, which would happily open
`/etc/passwd` for anyone who could get that string into a key column.

MISSING FILES are None, never an exception and never a 500. A source document
that has been deleted (Phase 11 retention) or lost to an ephemeral disk is an
ordinary state, and callers are expected to handle it.
"""

import logging
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Optional

from app.config import settings

log = logging.getLogger("docagent.storage")

ALLOWED_EXTENSIONS = {
    "pdf",
    "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp",
    "heic", "heif", "gif", "avif",
    "yml", "yaml",
}

#: A key is lowercase-ish path segments joined by "/". No leading slash, no
#: "..", no backslash, no drive letter, no empty segment.
_KEY_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")


class StorageError(Exception):
    """A storage operation failed in a way the caller must not ignore — a
    rejected key, or a write that did not happen. Reads never raise."""


def _safe_segment(value, fallback: str = "unknown") -> str:
    """One path segment, with everything dangerous removed rather than
    rejected — tenant ids and filenames come from the outside world."""
    name = Path(str(value or "")).name          # strips any directory part
    name = name.replace("\\", "_")
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._-") or fallback
    return name[:120]


def _tenant_segment(client_id, fallback: str) -> str:
    """A firm's id as the leading key segment — used AS IS or refused.

    `_safe_segment` normalises, which is right for a file name and wrong for a
    firm: `a b` and `a_b`, or `../acme` and `acme`, would share one prefix and
    one schema file, and every key built from one would name the other's
    files. A firm id that is not already a safe segment is refused, so two
    firms can never map to the same prefix. No id at all keeps the fallback.
    """
    if client_id is None or str(client_id) == "":
        return fallback
    cid = str(client_id)
    if _safe_segment(cid, fallback) != cid:
        raise StorageError("client_id is not a valid storage segment "
                           "(letters, digits, '.', '_' and '-' only)")
    return cid


def _safe_key(key: str) -> str:
    """Validate a whole key. Raises StorageError rather than silently
    normalising, because a key that needs normalising was built wrong."""
    k = str(key or "").strip().replace("\\", "/")
    if not k:
        raise StorageError("empty storage key")
    if k.startswith("/") or k.startswith("~") or re.match(r"^[A-Za-z]:", k):
        raise StorageError(f"absolute storage key rejected: {key!r}")
    segments = k.split("/")
    for seg in segments:
        if not seg or seg in (".", ".."):
            raise StorageError(f"unsafe segment in storage key: {key!r}")
        if not _KEY_SEGMENT.match(seg):
            raise StorageError(f"illegal character in storage key: {key!r}")
    return "/".join(segments)


#: Where object-store temp copies live. The app's OWN directory: the startup
#: sweep deletes stale files here and nowhere else.
TEMP_COPY_DIR = Path(tempfile.gettempdir()) / "docagent-storage-copies"
_TEMP_COPY_PREFIX = "copy-"
#: A temp copy older than this is a leak (a crashed worker), not a file in use.
STALE_COPY_AGE_SEC = 24 * 3600


class StorageService:
    """Unified file storage — local filesystem or S3-compatible object store."""

    def __init__(self):
        settings.ensure_storage_dirs()
        self._backend = settings.STORAGE_BACKEND
        self._client = None
        self.temp_dir = TEMP_COPY_DIR

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def root(self) -> Path:
        """Local storage root. Every key hangs off this directory."""
        return Path(settings.LOCAL_UPLOAD_DIR).parent

    # ─── Key construction (the ONLY place keys are made) ─────────────────────

    @staticmethod
    def upload_key(client_id, job_id, filename) -> str:
        return _safe_key(f"clients/{_tenant_segment(client_id, 'anon')}"
                         f"/jobs/{_safe_segment(job_id, '0')}"
                         f"/source/{_safe_segment(filename, 'file')}")

    @staticmethod
    def output_key(client_id, job_id, filename) -> str:
        return _safe_key(f"clients/{_tenant_segment(client_id, 'anon')}"
                         f"/jobs/{_safe_segment(job_id, '0')}"
                         f"/output/{_safe_segment(filename, 'file')}")

    @staticmethod
    def schema_key(client_id) -> str:
        return _safe_key(f"schemas/clients/{_tenant_segment(client_id, 'client')}.yaml")

    @staticmethod
    def job_prefix(client_id, job_id) -> str:
        return _safe_key(f"clients/{_tenant_segment(client_id, 'anon')}"
                         f"/jobs/{_safe_segment(job_id, '0')}")

    # ─── Write ───────────────────────────────────────────────────────────────

    def put(self, key: str, data: bytes) -> str:
        """Write bytes at `key`. Returns the key. Raises on failure — a write
        that did not happen must never look like one that did."""
        key = _safe_key(key)
        if isinstance(data, (bytes, bytearray)):
            payload = bytes(data)
        else:
            payload = data.read()
        try:
            if self._backend == "s3":
                self._s3().put_object(Bucket=settings.S3_BUCKET, Key=key,
                                      Body=payload)
            else:
                path = self._local_path(key)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(payload)
        except StorageError:
            raise
        except Exception as e:
            raise StorageError(f"could not write {key}: {e}") from e
        return key

    def save_upload(self, file_data: bytes | BinaryIO, filename: str,
                    job_id, client_id=None, user_id=None) -> tuple[str, str]:
        """Store an uploaded source document. Returns (key, key).

        The pair is kept for the existing call sites, but BOTH halves are now
        the key: a local absolute path is meaningless to a worker process or an
        object store, and passing one around is what tied extraction to the web
        container's own disk.
        """
        key = self.upload_key(client_id or user_id, job_id, filename)
        self.put(key, file_data)
        return key, key

    def save_output(self, file_data: bytes, filename: str, job_id,
                    client_id=None, user_id=None) -> tuple[str, str]:
        key = self.output_key(client_id or user_id, job_id, filename)
        self.put(key, file_data)
        return key, key

    def save_schema(self, yaml_content: str, client_id: str) -> tuple[str, str]:
        key = self.schema_key(client_id)
        self.put(key, yaml_content.encode("utf-8"))
        return key, key

    # ─── Read ────────────────────────────────────────────────────────────────

    def exists(self, key: str) -> bool:
        try:
            key = _safe_key(key)
        except StorageError:
            return False
        if self._backend == "s3":
            try:
                self._s3().head_object(Bucket=settings.S3_BUCKET, Key=key)
                return True
            except Exception:
                return False
        return self._local_path(key).exists()

    def get_bytes(self, key: str) -> Optional[bytes]:
        """File contents, or None if it is not there. Never raises."""
        try:
            key = _safe_key(key)
        except StorageError:
            return None
        try:
            if self._backend == "s3":
                obj = self._s3().get_object(Bucket=settings.S3_BUCKET, Key=key)
                return obj["Body"].read()
            path = self._local_path(key)
            return path.read_bytes() if path.exists() else None
        except Exception:
            return None

    def get_local_path(self, key: str) -> Optional[Path]:
        """A real filesystem path for `key`, or None if the file is gone.

        With the object store the file is fetched to a temp copy in
        `temp_dir`, because pdfplumber and pdf2image want a path. The caller
        OWNS that copy and must hand it back with `release()` (or use
        `local_copy()`): it is a client's document on the server's disk, and
        nothing else ever deleted it. On the local backend the path is the
        stored file itself, and `release()` leaves it alone.
        """
        try:
            key = _safe_key(key)
        except StorageError:
            return None
        if self._backend == "s3":
            data = self.get_bytes(key)
            if data is None:
                return None
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            tmp = tempfile.NamedTemporaryFile(delete=False, dir=self.temp_dir,
                                              prefix=_TEMP_COPY_PREFIX,
                                              suffix=Path(key).suffix)
            try:
                tmp.write(data)
            finally:
                tmp.close()
            return Path(tmp.name)
        path = self._local_path(key)
        return path if path.exists() else None

    def is_temp_copy(self, path) -> bool:
        """True only for a file `get_local_path` made in `temp_dir`."""
        if not path:
            return False
        try:
            p = Path(path)
            return (p.name.startswith(_TEMP_COPY_PREFIX)
                    and p.resolve().parent == Path(self.temp_dir).resolve())
        except (OSError, ValueError):
            return False

    def release(self, path) -> None:
        """Delete a temp copy `get_local_path` handed out. Anything else — the
        local store's own file, an uploaded path from an old job, None — is
        left exactly where it is. Never raises."""
        if not self.is_temp_copy(path):
            return
        try:
            Path(path).unlink(missing_ok=True)
        except OSError as e:
            log.warning("temp copy could not be removed (%s)", type(e).__name__)

    @contextmanager
    def local_copy(self, key: str):
        """`get_local_path` with the cleanup guaranteed: the copy is released
        on success, on an exception and on a cancelled job alike."""
        path = self.get_local_path(key)
        try:
            yield path
        finally:
            self.release(path)

    def sweep_temp_copies(self, max_age_sec: float = STALE_COPY_AGE_SEC,
                          now: Optional[float] = None) -> int:
        """Delete temp copies older than `max_age_sec`; returns how many.

        Restricted to `temp_dir`, to regular files carrying the copy prefix:
        no recursion, no symlinks followed, nothing outside the directory.
        Run at boot, when a copy that old can only have been leaked by a
        worker that died with the process."""
        d = Path(self.temp_dir)
        if not d.is_dir():
            return 0
        now = time.time() if now is None else now
        removed = 0
        for entry in d.iterdir():
            try:
                if (not entry.name.startswith(_TEMP_COPY_PREFIX)
                        or entry.is_symlink() or not entry.is_file()):
                    continue
                if now - entry.stat().st_mtime < max_age_sec:
                    continue
                entry.unlink()
                removed += 1
            except OSError:
                continue
        return removed

    def get_output_bytes(self, key: str) -> Optional[bytes]:
        return self.get_bytes(key)

    def get_schema_path(self, client_id: str) -> Optional[Path]:
        return self.get_local_path(self.schema_key(client_id))

    def signed_url(self, key: str, expires_in: int = 300) -> Optional[str]:
        """A short-lived direct download URL, or None on the local backend.

        Object storage can hand a browser a URL that expires; a filesystem
        cannot, and Phase 11 will need an app-served fallback for local
        development. Returning None rather than a permanent URL keeps the
        difference visible instead of quietly shipping a link that never
        expires.
        """
        if self._backend != "s3":
            return None
        try:
            return self._s3().generate_presigned_url(
                "get_object",
                Params={"Bucket": settings.S3_BUCKET, "Key": _safe_key(key)},
                ExpiresIn=max(1, min(int(expires_in), 3600)),
            )
        except Exception:
            return None

    # ─── Delete ──────────────────────────────────────────────────────────────

    def delete(self, key: str) -> bool:
        """Remove one object. True if it is gone afterwards (including when it
        was already absent)."""
        try:
            key = _safe_key(key)
        except StorageError:
            return False
        try:
            if self._backend == "s3":
                self._s3().delete_object(Bucket=settings.S3_BUCKET, Key=key)
                return True
            path = self._local_path(key)
            if path.exists():
                path.unlink()
            return True
        except Exception:
            return False

    def delete_prefix(self, prefix: str) -> int:
        """Remove everything under a prefix. Returns how many objects went.

        This is what Phase 11's "delete the source document, keep the extracted
        values" is built on: the values live in the database, the sources live
        under a job prefix, and the two are deleted independently.
        """
        try:
            prefix = _safe_key(prefix)
        except StorageError:
            return 0
        n = 0
        try:
            if self._backend == "s3":
                client = self._s3()
                token = None
                while True:
                    kw = {"Bucket": settings.S3_BUCKET, "Prefix": prefix + "/"}
                    if token:
                        kw["ContinuationToken"] = token
                    page = client.list_objects_v2(**kw)
                    keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
                    if keys:
                        client.delete_objects(Bucket=settings.S3_BUCKET,
                                              Delete={"Objects": keys})
                        n += len(keys)
                    if not page.get("IsTruncated"):
                        break
                    token = page.get("NextContinuationToken")
            else:
                d = self._local_path(prefix)
                if d.is_dir():
                    n = sum(1 for p in d.rglob("*") if p.is_file())
                    shutil.rmtree(d, ignore_errors=True)
        except Exception:
            return n
        return n

    def count_prefix(self, prefix: str) -> int:
        """How many objects are stored under a prefix — what a delete checks
        afterwards, because `delete_prefix` reports what it attempted, and a
        delete that half-failed must not be reported as done. Raises
        StorageError when the store cannot be listed."""
        prefix = _safe_key(prefix)
        try:
            if self._backend == "s3":
                page = self._s3().list_objects_v2(Bucket=settings.S3_BUCKET,
                                                  Prefix=prefix + "/", MaxKeys=1)
                return len(page.get("Contents", []))
            d = self._local_path(prefix)
            return sum(1 for p in d.rglob("*") if p.is_file()) if d.is_dir() else 0
        except Exception as e:
            raise StorageError(f"cannot list storage ({type(e).__name__})")

    def delete_job_sources(self, client_id, job_id) -> int:
        """Delete a job's SOURCE documents, leaving its outputs alone."""
        return self.delete_prefix(f"{self.job_prefix(client_id, job_id)}/source")


    # ─── Validation ──────────────────────────────────────────────────────────

    def validate_upload(self, filename: str, size: int) -> Optional[str]:
        if size == 0:
            return "File is empty."
        if size > settings.max_upload_bytes:
            return (f"File too large ({size / 1024 / 1024:.1f}MB). "
                    f"Max: {settings.MAX_UPLOAD_SIZE_MB}MB")
        return None

    # ─── Internals ───────────────────────────────────────────────────────────

    def _local_path(self, key: str) -> Path:
        """Key -> filesystem path, guaranteed to stay inside the root.

        The containment check is belt-and-braces: `_safe_key` already rejects
        `..`, and this re-checks the resolved path, because a traversal that
        reaches the filesystem is unrecoverable while an extra `resolve()` is
        free.
        """
        root = self.root.resolve()
        path = (root / key).resolve()
        if not str(path).startswith(str(root)):
            raise StorageError(f"storage key escapes the root: {key!r}")
        return path

    def _s3(self):
        if self._client is None:
            import boto3
            kwargs = {
                "aws_access_key_id": settings.AWS_ACCESS_KEY_ID,
                "aws_secret_access_key": settings.AWS_SECRET_ACCESS_KEY,
                "region_name": settings.AWS_REGION,
            }
            if settings.S3_ENDPOINT_URL:
                kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
            self._client = boto3.client("s3", **kwargs)
        return self._client


# Singleton
_storage: Optional[StorageService] = None


def get_storage() -> StorageService:
    global _storage
    if _storage is None:
        _storage = StorageService()
    return _storage


