"""
DocAgent — Drive Watcher (v2 compatible)
Polls watched Google Drive folders for new files and auto-processes them.
"""

import sys
import time
import shutil
import tempfile
import argparse
from pathlib import Path
from datetime import datetime

# Ensure engine root is on sys.path so sibling imports resolve
_ENGINE_DIR = Path(__file__).resolve().parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from config import settings, BASE_DIR
from storage.database import Database


def check_watched_folders(db: Database, verbose: bool = True):
    """Check all active watch folders for new files and process them."""
    try:
        from connectors.gdrive import get_drive_connector
    except ImportError:
        if verbose:
            print("[Watcher] Google Drive connector not available.")
        return 0

    drive = get_drive_connector()

    if not drive.is_configured or not drive.is_authenticated:
        if verbose:
            print("[Watcher] Google Drive not configured or not authenticated.")
        return 0

    watch_folders = db.get_watch_folders()
    if not watch_folders:
        if verbose:
            print("[Watcher] No watched folders configured.")
        return 0

    total_new = 0

    for wf in watch_folders:
        if verbose:
            print(f"[Watcher] Checking: {wf['folder_name']}")

        files = drive.list_files(wf["folder_id"])
        current_ids = {f.id for f in files}
        processed_ids = set(wf["processed_file_ids"])

        new_files = [f for f in files if f.id not in processed_ids]

        if not new_files:
            if verbose:
                print(f"  No new files. ({len(files)} total, {len(processed_ids)} processed)")
            db.update_watch_folder(wf["id"], list(processed_ids & current_ids), len(files))
            continue

        if verbose:
            print(f"  Found {len(new_files)} new files!")

        temp_dir = Path(tempfile.mkdtemp(prefix="docagent_watch_"))
        downloaded = []

        try:
            for f in new_files:
                if verbose:
                    print(f"    Downloading: {f.name}")
                path = drive.download_file(f.id, f.name, temp_dir)
                if path:
                    downloaded.append((f.id, path))

            if downloaded:
                # v2: resolve schema path via app storage service
                try:
                    from app.core.storage import get_storage
                    storage = get_storage()
                    schema_path = storage.get_schema_path(wf["client_id"])
                except ImportError:
                    # Fallback for standalone execution
                    schema_path = settings.LOCAL_SCHEMAS_DIR / "clients" / f"{wf['client_id']}.yaml"
                    if not schema_path.exists():
                        schema_path = settings.LOCAL_SCHEMAS_DIR / "clients" / f"{wf['client_id']}.yml"

                if not schema_path or not schema_path.exists():
                    if verbose:
                        print(f"  ERROR: Schema not found for client '{wf['client_id']}'")
                    continue

                if verbose:
                    print(f"  Processing {len(downloaded)} files...")

                # orchestrator.py is at engine root — import directly
                from orchestrator import Orchestrator
                orchestrator = Orchestrator(client_schema_path=schema_path)
                file_paths = [path for _, path in downloaded]
                result = orchestrator.process_files(file_paths=file_paths)

                if verbose:
                    print(f"  Result: {result.successful}/{result.total_docs} successful")

                if result.output_file:
                    try:
                        upload_id = drive.upload_file(result.output_file, wf["folder_id"])
                        if upload_id and verbose:
                            print("  Uploaded results to Drive!")
                    except Exception as e:
                        if verbose:
                            print(f"  Upload failed: {e}")

                new_processed = processed_ids | {fid for fid, _ in downloaded}
                db.update_watch_folder(wf["id"], list(new_processed & current_ids), len(files))
                total_new += len(downloaded)

        except Exception as e:
            if verbose:
                print(f"  ERROR: {e}")
            import traceback
            if verbose:
                traceback.print_exc()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    return total_new


def run_loop(interval_minutes: int = 5):
    """Continuously poll watched folders."""
    db = Database()
    print(f"[Watcher] Starting (every {interval_minutes} min). Ctrl+C to stop.")

    while True:
        try:
            now = datetime.now().strftime("%H:%M:%S")
            print(f"\n[{now}] Checking...")
            new_count = check_watched_folders(db)
            if new_count:
                print(f"  Processed {new_count} new files")
        except KeyboardInterrupt:
            print("\n[Watcher] Stopped.")
            break
        except Exception as e:
            print(f"[Watcher] Error: {e}")

        time.sleep(interval_minutes * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DocAgent Drive Watcher")
    parser.add_argument("--loop", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in minutes")
    args = parser.parse_args()

    if args.loop:
        run_loop(args.interval)
    else:
        db = Database()
        check_watched_folders(db)
