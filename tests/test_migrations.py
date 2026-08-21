"""
A migration that does not run must say so.

The previous `_run_migrations` wrapped every statement in `except Exception`,
logged the failure at DEBUG — invisible at production log level — and then
printed "Database migrations applied" whether anything had applied or not.
That is precisely how `column_templates.description` stayed VARCHAR(500)
against an ORM that declared Text: the repair never ran, every real template
save failed with StringDataRightTruncation, and the startup log said the
migrations were fine.

Three properties are pinned here: failures are visible, the summary reports
real counts, and production refuses to serve on a schema that did not apply.
"""
import logging

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


class _Boom(Exception):
    pass


@pytest.fixture
def run(monkeypatch):
    """Drive _run_migrations against a fake session whose statements can be
    made to fail on demand."""
    import app.main as m

    def _go(*, dialect="postgresql", fail_on=(), production=False):
        executed = []

        class _Dialect:
            name = dialect

        class _Bind:
            dialect = _Dialect()

        class _DB:
            bind = _Bind()

            def execute(self, stmt):
                sql = " ".join(str(stmt).split())
                executed.append(sql)
                for needle in fail_on:
                    if needle in sql:
                        raise _Boom(f"permission denied for relation ({needle})")

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        monkeypatch.setattr("app.models.SessionLocal", lambda: _DB())
        monkeypatch.setattr(m.settings, "ENVIRONMENT",
                            "production" if production else "development")
        return m._run_migrations, executed

    return _go


class TestFailuresAreVisible:
    def test_a_failing_migration_is_logged_at_error(self, run, caplog):
        go, _ = run(fail_on=("ALTER COLUMN description",))
        with caplog.at_level(logging.DEBUG):
            go()
        errs = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert errs, "a failed migration produced no ERROR record"
        assert any("MIGRATION FAILED" in r.getMessage() for r in errs)

    def test_the_failing_statement_and_the_cause_are_both_named(self, run, caplog):
        """A log line saying 'a migration failed' is not actionable. It has to
        say which one and why."""
        go, _ = run(fail_on=("ALTER COLUMN description",))
        with caplog.at_level(logging.DEBUG):
            go()
        blob = "\n".join(r.getMessage() for r in caplog.records)
        assert "ALTER COLUMN description" in blob
        assert "permission denied" in blob

    def test_nothing_is_logged_at_debug_only(self, run, caplog):
        """The original bug: DEBUG is invisible in production, so the failure
        may as well not have been logged."""
        go, _ = run(fail_on=("ALTER COLUMN description",))
        with caplog.at_level(logging.INFO):
            go()
        assert any(r.levelno >= logging.ERROR for r in caplog.records)


class TestTheSummaryTellsTheTruth:
    def test_it_does_not_claim_success_when_a_migration_failed(self, run, caplog):
        go, _ = run(fail_on=("ALTER COLUMN description",))
        with caplog.at_level(logging.DEBUG):
            go()
        for r in caplog.records:
            msg = r.getMessage()
            if "0 failed" in msg:
                pytest.fail(f"claimed success while a migration failed: {msg}")

    def test_counts_are_real(self, run):
        go, _ = run(fail_on=("ALTER COLUMN description",))
        res = go()
        assert res["failed"] == 1
        assert res["applied"] >= 1

    def test_a_clean_run_reports_zero_failures(self, run):
        go, executed = run()
        res = go()
        assert res["failed"] == 0
        assert res["applied"] == len(executed) > 5

    def test_the_description_repair_is_actually_among_them(self, run):
        """The specific statement whose silent absence caused the bug."""
        go, executed = run()
        go()
        assert any("ALTER COLUMN description TYPE TEXT" in s for s in executed)


class TestDialectSkipIsStatedNotSwallowed:
    def test_sqlite_skips_loudly(self, run, caplog):
        """Every statement is PostgreSQL syntax. Skipping on SQLite is
        correct — being quiet about it is what was wrong."""
        go, executed = run(dialect="sqlite")
        with caplog.at_level(logging.DEBUG):
            res = go()
        assert executed == [], "PostgreSQL syntax was run against SQLite"
        assert res["applied"] == 0 and res["failed"] == 0
        warns = [r.getMessage() for r in caplog.records
                 if r.levelno >= logging.WARNING]
        assert any("SKIPPED" in m for m in warns), warns

    def test_a_dialect_skip_is_not_a_failure(self, run):
        res = run(dialect="sqlite")[0]()
        assert res["failed"] == 0


class TestProductionRefusesAnUnverifiedSchema:
    def test_a_failure_in_production_raises(self, run):
        go, _ = run(fail_on=("ALTER COLUMN description",), production=True)
        with pytest.raises(RuntimeError) as e:
            go()
        assert "migration" in str(e.value).casefold()
        assert "ALTER COLUMN description" in str(e.value)

    def test_the_same_failure_in_development_does_not_raise(self, run):
        """Local work must not be blocked by a migration that cannot apply
        to a developer's database."""
        res = run(fail_on=("ALTER COLUMN description",), production=False)[0]()
        assert res["failed"] == 1

    def test_production_with_no_failures_does_not_raise(self, run):
        res = run(production=True)[0]()
        assert res["failed"] == 0

    def test_sqlite_in_production_does_not_raise(self, run):
        """A dialect skip is not a failed migration, even in production."""
        assert run(dialect="sqlite", production=True)[0]()["failed"] == 0
