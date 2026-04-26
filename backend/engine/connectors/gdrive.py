"""
DocAgent — Google Drive Connector
Handles Google Drive integration:
  - OAuth2 authentication flow
  - List files in a Drive folder
  - Download files to local temp directory for processing
  - Upload results back to Drive

Setup:
  1. Go to https://console.cloud.google.com
  2. Create a project (or use existing)
  3. Enable Google Drive API
  4. Create OAuth 2.0 credentials (Desktop app type)
  5. Download credentials.json -> place in docagent root
  6. Add your email as a test user in OAuth consent screen
"""

import io
import os
import json
import tempfile
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field

from backend.engine.config import settings, BASE_DIR  # BASE_DIR is module-level, NOT on settings


@dataclass
class DriveFile:
    """Represents a file in Google Drive."""
    id: str
    name: str
    mime_type: str = ""
    size: int = 0
    created_time: str = ""
    modified_time: str = ""
    parents: list[str] = field(default_factory=list)

    @property
    def is_supported(self) -> bool:
        supported_mimes = {
            "application/pdf",
            "image/png", "image/jpeg", "image/jpg",
            "image/tiff", "image/bmp", "image/webp",
        }
        supported_exts = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp", ".heic"}
        if self.mime_type in supported_mimes:
            return True
        ext = Path(self.name).suffix.lower()
        return ext in supported_exts


@dataclass
class DriveFolder:
    id: str
    name: str
    path: str = ""


# Read + write scope so we can upload results back to Drive
SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]
CREDENTIALS_FILE = "credentials.json"
TOKEN_FILE = "token.json"


class GoogleDriveConnector:
    """Google Drive integration for DocAgent."""

    def __init__(self):
        self._service = None
        self._creds = None
        # Use module-level BASE_DIR, not settings.BASE_DIR
        self._credentials_path = BASE_DIR / CREDENTIALS_FILE
        self._token_path = BASE_DIR / TOKEN_FILE

    @property
    def is_configured(self) -> bool:
        """Check if Google Drive credentials file exists."""
        return self._credentials_path.exists()

    @property
    def is_authenticated(self) -> bool:
        """Check if we have a valid token."""
        if self._creds and self._creds.valid:
            return True
        if self._token_path.exists():
            try:
                self._load_token()
                return self._creds is not None and self._creds.valid
            except Exception:
                return False
        return False

    def authenticate(self) -> bool:
        """Run the OAuth2 authentication flow.
        Returns True if authentication was successful."""
        try:
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from google.auth.transport.requests import Request

            creds = None

            # Load existing token
            if self._token_path.exists():
                try:
                    creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
                except Exception:
                    # Token file corrupted, delete and re-auth
                    self._token_path.unlink(missing_ok=True)
                    creds = None

            # Refresh or create new token
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    try:
                        creds.refresh(Request())
                    except Exception:
                        # Refresh failed, need full re-auth
                        self._token_path.unlink(missing_ok=True)
                        creds = None

                if not creds or not creds.valid:
                    if not self._credentials_path.exists():
                        print(f"[Drive] credentials.json not found at: {self._credentials_path}")
                        return False

                    # Allow running in environments where browser can't open
                    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

                    flow = InstalledAppFlow.from_client_secrets_file(
                        str(self._credentials_path), SCOPES
                    )
                    try:
                        creds = flow.run_local_server(
                            port=8090,
                            open_browser=True,
                            success_message="Authentication successful! You can close this window.",
                        )
                    except OSError:
                        # Port 8090 busy, try another
                        creds = flow.run_local_server(
                            port=0,  # Random available port
                            open_browser=True,
                            success_message="Authentication successful! You can close this window.",
                        )

                # Save the token
                if creds:
                    with open(self._token_path, "w") as f:
                        f.write(creds.to_json())

            self._creds = creds
            self._service = None  # Reset service so it rebuilds with new creds
            return creds is not None and creds.valid

        except Exception as e:
            print(f"[Drive Auth Error] {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _get_service(self):
        """Get or create the Drive API service."""
        if self._service is None:
            from googleapiclient.discovery import build
            if not self._creds:
                self._load_token()
            if not self._creds:
                raise RuntimeError("Not authenticated. Call authenticate() first.")
            self._service = build("drive", "v3", credentials=self._creds)
        return self._service

    def _load_token(self):
        """Load credentials from saved token."""
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        if self._token_path.exists():
            try:
                self._creds = Credentials.from_authorized_user_file(str(self._token_path), SCOPES)
                if self._creds and self._creds.expired and self._creds.refresh_token:
                    self._creds.refresh(Request())
                    with open(self._token_path, "w") as f:
                        f.write(self._creds.to_json())
            except Exception as e:
                print(f"[Drive] Token load/refresh failed: {e}")
                self._creds = None
                # Delete corrupted token so next auth starts fresh
                self._token_path.unlink(missing_ok=True)

    def list_folders(self, parent_id: str = "root") -> list[DriveFolder]:
        """List folders in a given parent folder."""
        try:
            service = self._get_service()
            query = f"'{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
            results = service.files().list(
                q=query,
                fields="files(id, name)",
                orderBy="name",
                pageSize=100,
            ).execute()
            return [DriveFolder(id=f["id"], name=f["name"]) for f in results.get("files", [])]
        except Exception as e:
            print(f"[Drive Error] List folders: {e}")
            return []

    def list_files(self, folder_id: str = "root") -> list[DriveFile]:
        """List all supported files in a Drive folder."""
        try:
            service = self._get_service()
            query = f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'"
            results = service.files().list(
                q=query,
                fields="files(id, name, mimeType, size, createdTime, modifiedTime, parents)",
                orderBy="name",
                pageSize=200,
            ).execute()
            files = []
            for f in results.get("files", []):
                df = DriveFile(
                    id=f["id"], name=f["name"],
                    mime_type=f.get("mimeType", ""),
                    size=int(f.get("size", 0)),
                    created_time=f.get("createdTime", ""),
                    modified_time=f.get("modifiedTime", ""),
                    parents=f.get("parents", []),
                )
                if df.is_supported:
                    files.append(df)
            return files
        except Exception as e:
            print(f"[Drive Error] List files: {e}")
            return []

    def download_file(self, file_id: str, filename: str, dest_dir: str | Path) -> Optional[Path]:
        """Download a single file from Drive to local directory."""
        try:
            from googleapiclient.http import MediaIoBaseDownload
            service = self._get_service()
            request = service.files().get_media(fileId=file_id)
            dest_dir = Path(dest_dir)
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / filename
            with open(dest_path, "wb") as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
            return dest_path
        except Exception as e:
            print(f"[Drive Error] Download {filename}: {e}")
            return None

    def download_folder_files(self, folder_id: str, dest_dir: str | Path, progress_callback=None) -> list[Path]:
        """Download all supported files from a Drive folder."""
        files = self.list_files(folder_id)
        downloaded = []
        for i, f in enumerate(files):
            if progress_callback:
                progress_callback(i, len(files), f.name)
            path = self.download_file(f.id, f.name, dest_dir)
            if path:
                downloaded.append(path)
        return downloaded

    def upload_file(self, local_path: str | Path, folder_id: str = "root", mime_type: str = None) -> Optional[str]:
        """Upload a file to a Drive folder. Returns the file ID."""
        try:
            from googleapiclient.http import MediaFileUpload
            service = self._get_service()
            local_path = Path(local_path)
            if mime_type is None:
                ext = local_path.suffix.lower()
                mime_map = {
                    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    ".pdf": "application/pdf",
                    ".csv": "text/csv",
                }
                mime_type = mime_map.get(ext, "application/octet-stream")
            file_metadata = {"name": local_path.name, "parents": [folder_id]}
            media = MediaFileUpload(str(local_path), mimetype=mime_type)
            result = service.files().create(body=file_metadata, media_body=media, fields="id").execute()
            return result.get("id")
        except Exception as e:
            print(f"[Drive Error] Upload {local_path}: {e}")
            return None


def get_drive_connector() -> GoogleDriveConnector:
    """Factory function to get a Drive connector instance."""
    return GoogleDriveConnector()