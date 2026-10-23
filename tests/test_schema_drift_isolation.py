from pathlib import Path

import pytest


def test_schema_drift_owns_a_throwaway_database_lifecycle():
    """Drift checks must never inspect or write the configured dev database."""
    source = (Path(__file__).with_name("test_schema_drift.py")
              .read_text(encoding="utf-8"))

    assert "CREATE DATABASE" in source
    assert "DROP DATABASE" in source
    assert "from app.models import SessionLocal" not in source


def test_missing_postgres_skips_unless_ci_requires_it(monkeypatch):
    from tests import test_schema_drift as drift

    monkeypatch.setattr(drift, "_find_postgres_binaries", lambda: (None, None))
    monkeypatch.delenv("DOCAGENT_REQUIRE_PG", raising=False)
    with pytest.raises(pytest.skip.Exception, match="PostgreSQL binaries"):
        drift._postgres_binaries()

    monkeypatch.setenv("DOCAGENT_REQUIRE_PG", "1")
    with pytest.raises(pytest.fail.Exception, match="DOCAGENT_REQUIRE_PG=1"):
        drift._postgres_binaries()
