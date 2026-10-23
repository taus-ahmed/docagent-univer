"""
The database must match what the ORM declares.

`create_all()` creates tables but NEVER alters an existing column. So a column
whose type changed in the model years ago keeps its original definition in every
database created before the change, and nothing says so. That is how
`column_templates.description` stayed `VARCHAR(500)` in local databases while
the ORM declared `Text` and production held 15,873-character grids: every real
template save failed with StringDataRightTruncation — a 500 with no clue in the
UI, and no template ever stored.

The tests never inspect or write the configured application database. They
start a private PostgreSQL cluster under pytest's temporary directory, create
a uniquely named throwaway database, build the legacy schema there, run the
startup migrations, assert against it, and stop and remove it at teardown.
"""
import json
import shutil
import socket
import subprocess
import uuid
from pathlib import Path

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

@pytest.fixture(scope="module")
def drift_database(tmp_path_factory):
    """A legacy database owned by this test, migrated and always dropped."""
    import sqlalchemy as sa
    from sqlalchemy.engine import make_url
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool
    from app.models.models import Base

    install_bins = sorted(
        Path("C:/Program Files/PostgreSQL").glob("*/bin"), reverse=True)
    initdb = shutil.which("initdb") or next(
        (str(p / "initdb.exe") for p in install_bins
         if (p / "initdb.exe").is_file()), None)
    pg_ctl = shutil.which("pg_ctl") or next(
        (str(p / "pg_ctl.exe") for p in install_bins
         if (p / "pg_ctl.exe").is_file()), None)
    if not initdb or not pg_ctl:
        pytest.fail("schema drift isolation requires local PostgreSQL binaries")

    cluster = tmp_path_factory.mktemp("schema_drift_postgres")
    data_dir = cluster / "data"
    log_path = cluster / "postgres.log"
    subprocess.run(
        [initdb, "-D", str(data_dir), "--auth=trust", "--encoding=UTF8",
         "--no-locale", "--username=postgres"],
        check=True, capture_output=True, text=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    subprocess.run(
        [pg_ctl, "-D", str(data_dir), "-l", str(log_path), "-o",
         f"-F -p {port} -h 127.0.0.1", "-w", "start"],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    database_name = f"docagent_drift_{uuid.uuid4().hex}"
    admin_url = make_url(
        f"postgresql+psycopg2://postgres@127.0.0.1:{port}/postgres")
    test_url = admin_url.set(database=database_name)
    admin = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT",
                             poolclass=NullPool)
    engine = None
    patch = pytest.MonkeyPatch()
    created = False
    try:
        with admin.connect() as connection:
            connection.execute(sa.text(f'CREATE DATABASE "{database_name}"'))
        created = True
        engine = sa.create_engine(test_url, pool_pre_ping=True, poolclass=NullPool)
        Base.metadata.create_all(engine)

        # Reproduce the two known legacy states. create_all() cannot repair
        # either one; the production startup migrations must do that.
        with engine.begin() as connection:
            connection.execute(sa.text(
                "ALTER TABLE column_templates "
                "ALTER COLUMN description TYPE VARCHAR(500)"))
            connection.execute(sa.text(
                "ALTER TABLE document_results DROP COLUMN original_filename"))

        isolated_session = sessionmaker(autocommit=False, autoflush=False,
                                        bind=engine)
        import app.models as models
        patch.setattr(models, "SessionLocal", isolated_session)
        from app.main import _run_migrations
        outcome = _run_migrations()
        assert outcome["failed"] == 0, outcome
        yield engine, isolated_session
    except Exception as exc:
        pytest.fail("isolated schema drift database failed: "
                    f"{type(exc).__name__}")
    finally:
        patch.undo()
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.execute(sa.text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"),
                    {"name": database_name})
                connection.execute(sa.text(f'DROP DATABASE "{database_name}"'))
        admin.dispose()
        subprocess.run(
            [pg_ctl, "-D", str(data_dir), "-m", "fast", "-w", "stop"],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


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
    def test_no_column_is_narrower_in_the_database_than_the_orm_declares(
            self, drift_database):
        """The truncation class. A DB column shorter than the ORM's type
        accepts short values and rejects real ones, so it passes every smoke
        test and fails on the first genuine template."""
        import sqlalchemy as sa
        from app.models.models import Base
        e, _session = drift_database
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

    def test_no_declared_column_is_missing_from_the_database(
            self, drift_database):
        import sqlalchemy as sa
        from app.models.models import Base
        e, _session = drift_database
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

    def test_nullability_matches(self, drift_database):
        import sqlalchemy as sa
        from app.models.models import Base
        e, _session = drift_database
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
    def test_a_realistic_grid_round_trips_through_the_database(
            self, drift_database):
        """The actual failure: a template grid is JSON of the whole sheet and
        runs to thousands of characters. A 500-char column takes the smoke test
        and rejects every real template."""
        import sqlalchemy as sa
        from app.models.models import ColumnTemplate
        _engine, isolated_session = drift_database

        cells = {}
        for r in range(40):
            cells[f"{r},0"] = {"value": f"A reasonably long field label {r}",
                               "style": {}}
            cells[f"{r},1"] = {"value": "", "style": {}}
        grid = json.dumps({"cells": cells, "colWidths": [200, 140],
                           "merges": {}, "repeatRows": []})
        assert len(grid) > 2000, "the probe grid must be bigger than 500 chars"

        db = isolated_session()
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
