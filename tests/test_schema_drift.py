"""
The database must match what the ORM declares.

`create_all()` creates tables but NEVER alters an existing column. So a column
whose type changed in the model years ago keeps its original definition in every
database created before the change, and nothing says so. That is how
`column_templates.description` stayed `VARCHAR(500)` in local databases while
the ORM declared `Text` and production held 15,873-character grids: every real
template save failed with StringDataRightTruncation — a 500 with no clue in the
UI, and no template ever stored.

These tests run against whatever DATABASE_URL is configured. If it is not
reachable they FAIL, because a run that checked nothing must not look like a
run that checked everything — see `_engine` below. Set DOCAGENT_DB_OPTIONAL=1
to skip on purpose.
"""
import json
import os
import warnings

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

# Opting out of the drift check must be a decision someone made, not a
# side effect of not having Postgres running.
_OPT_OUT = "DOCAGENT_DB_OPTIONAL"


def _engine():
    """The configured database, or a FAILURE saying the check did not run.

    This used to `pytest.skip` when no database was reachable, which made a
    run that verified nothing indistinguishable from a run that verified
    everything: five green skips in a 300-test suite, scrolling past. In CI
    without Postgres the drift check has never run at all and the build is
    still green — which is the same shape of problem as the migrations that
    logged their failures at DEBUG.

    A skip is still available, but it has to be asked for:

        DOCAGENT_DB_OPTIONAL=1 pytest

    and it is reported at every level pytest offers.
    """
    import sqlalchemy as sa
    from app.config import settings
    try:
        e = sa.create_engine(settings.DATABASE_URL, pool_pre_ping=True)
        with e.connect():
            pass
        return e
    except Exception as exc:
        reason = (f"schema drift NOT CHECKED: no reachable database "
                  f"({type(exc).__name__}: {str(exc)[:120]})")
        if os.getenv(_OPT_OUT) == "1":
            warnings.warn(reason, stacklevel=2)
            print(f"\n!! {reason}", flush=True)
            pytest.skip(reason)
        pytest.fail(
            reason + "\n\nThe ORM-vs-database check cannot run without a "
            "database, and a run that checked nothing must not report "
            "success — that is how column_templates.description stayed "
            "VARCHAR(500) for months.\n"
            "Either start the database (docker-compose up -d), point "
            "DATABASE_URL at one, or opt out on purpose with "
            f"{_OPT_OUT}=1.")


def _norm(t):
    s = str(t).upper().split("(")[0]
    return {"DATETIME": "TIMESTAMP", "DOUBLE PRECISION": "FLOAT",
            "CHARACTER VARYING": "VARCHAR"}.get(s, s)


def _len(t):
    s = str(t)
    if "(" not in s:
        return None
    inner = s.split("(")[1].rstrip(")")
    return int(inner) if inner.isdigit() else None


class TestOrmMatchesDatabase:
    def test_no_column_is_narrower_in_the_database_than_the_orm_declares(self):
        """The truncation class. A DB column shorter than the ORM's type
        accepts short values and rejects real ones, so it passes every smoke
        test and fails on the first genuine template."""
        import sqlalchemy as sa
        from app.models.models import Base
        e = _engine()
        insp = sa.inspect(e)
        bad = []
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            db_cols = {c["name"]: c for c in insp.get_columns(table.name)}
            for col in table.columns:
                d = db_cols.get(col.name)
                if d is None:
                    continue
                if _norm(col.type) == "TEXT" and _norm(d["type"]) == "VARCHAR":
                    bad.append(f"{table.name}.{col.name}: ORM=TEXT DB={d['type']}")
                    continue
                ol, dl = _len(col.type), _len(d["type"])
                if ol and dl and dl < ol:
                    bad.append(f"{table.name}.{col.name}: ORM={ol} DB={dl}")
        assert not bad, (
            "Database columns narrower than the ORM declares — every value "
            "longer than the DB limit will fail to save:\n  " + "\n  ".join(bad))

    def test_no_declared_column_is_missing_from_the_database(self):
        import sqlalchemy as sa
        from app.models.models import Base
        e = _engine()
        insp = sa.inspect(e)
        missing = []
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have:
                    missing.append(f"{table.name}.{col.name}")
        assert not missing, f"declared but absent from the DB: {missing}"

    def test_nullability_matches(self):
        import sqlalchemy as sa
        from app.models.models import Base
        e = _engine()
        insp = sa.inspect(e)
        bad = []
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            db_cols = {c["name"]: c for c in insp.get_columns(table.name)}
            for col in table.columns:
                d = db_cols.get(col.name)
                if d is None or col.primary_key:
                    continue
                if bool(col.nullable) != bool(d.get("nullable", True)):
                    bad.append(f"{table.name}.{col.name}: ORM nullable="
                               f"{col.nullable} DB nullable={d.get('nullable')}")
        assert not bad, f"nullability drift: {bad}"


class TestTemplateGridFits:
    def test_a_realistic_grid_round_trips_through_the_database(self):
        """The actual failure: a template grid is JSON of the whole sheet and
        runs to thousands of characters. A 500-char column takes the smoke test
        and rejects every real template."""
        import sqlalchemy as sa
        from app.models import SessionLocal
        from app.models.models import ColumnTemplate
        _engine()

        cells = {}
        for r in range(40):
            cells[f"{r},0"] = {"value": f"A reasonably long field label {r}",
                               "style": {}}
            cells[f"{r},1"] = {"value": "", "style": {}}
        grid = json.dumps({"cells": cells, "colWidths": [200, 140],
                           "merges": {}, "repeatRows": []})
        assert len(grid) > 2000, "the probe grid must be bigger than 500 chars"

        db = SessionLocal()
        tpl = ColumnTemplate(name="__drift_probe__", document_type="other",
                             description=grid, columns_json="[]")
        try:
            db.add(tpl)
            db.commit()
            db.refresh(tpl)
            assert tpl.description == grid, "grid did not round-trip intact"
        except sa.exc.DataError as exc:
            pytest.fail(
                f"a {len(grid)}-character template grid cannot be stored: {exc}. "
                f"Run the startup migration (ALTER COLUMN description TYPE TEXT).")
        finally:
            db.rollback()          # a failed flush poisons the session
            db.query(ColumnTemplate).filter(
                ColumnTemplate.name == "__drift_probe__").delete()
            db.commit()
            db.close()


class TestMigrationIsPresent:
    def test_the_description_widening_is_in_the_startup_migrations(self):
        """Belt and braces: even where no database is reachable, the repair
        must still be in the migration list."""
        src = (bs.BACKEND_DIR / "app" / "main.py").read_text(encoding="utf-8")
        assert "ALTER COLUMN description TYPE TEXT" in src
