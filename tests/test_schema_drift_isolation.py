from pathlib import Path


def test_schema_drift_owns_a_throwaway_database_lifecycle():
    """Drift checks must never inspect or write the configured dev database."""
    source = (Path(__file__).with_name("test_schema_drift.py")
              .read_text(encoding="utf-8"))

    assert "CREATE DATABASE" in source
    assert "DROP DATABASE" in source
    assert "from app.models import SessionLocal" not in source
