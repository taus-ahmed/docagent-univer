"""
engine/storage/database.py — No-op stub for v2.

The prototype Orchestrator.__init__ calls Database() and uses it in
process_folder() / process_files(). In v2 we call _process_single_document()
directly and handle persistence in the FastAPI layer, so the prototype Database
is never actually used.

This stub satisfies the import without pulling in SQLite or any prototype DB logic.
"""


class Database:
    """No-op database stub. v2 uses app/models/models.py + PostgreSQL instead."""

    def __init__(self):
        pass

    def create_job(self, *args, **kwargs):
        return 0

    def add_document_result(self, *args, **kwargs):
        return 0

    def complete_job(self, *args, **kwargs):
        pass

    def fail_job(self, *args, **kwargs):
        pass

    def get_all_jobs(self, *args, **kwargs):
        return []

    def get_job_documents(self, *args, **kwargs):
        return []

    def update_document_data(self, *args, **kwargs):
        pass

    def approve_document(self, *args, **kwargs):
        pass

    def authenticate(self, *args, **kwargs):
        return None

    def create_user(self, *args, **kwargs):
        return None

    def get_all_users(self, *args, **kwargs):
        return []

    def update_user(self, *args, **kwargs):
        pass

    def delete_user(self, *args, **kwargs):
        pass

    def add_watch_folder(self, *args, **kwargs):
        return 0

    def get_watch_folders(self, *args, **kwargs):
        return []

    def update_watch_folder(self, *args, **kwargs):
        pass

    def remove_watch_folder(self, *args, **kwargs):
        pass

    def save_column_template(self, *args, **kwargs):
        return 0

    def get_column_templates(self, *args, **kwargs):
        return []

    def delete_column_template(self, *args, **kwargs):
        pass

    def get_stats(self, *args, **kwargs):
        return {}
