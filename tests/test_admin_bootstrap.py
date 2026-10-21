"""Contract for explicit, one-time administrator bootstrap."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from tests.harness import bootstrap as bs

bs.bootstrap()

USERNAME_ENV = "DOCAGENT_BOOTSTRAP_ADMIN_USERNAME"
PASSWORD_ENV = "DOCAGENT_BOOTSTRAP_ADMIN_PASSWORD"
DISPLAY_NAME_ENV = "DOCAGENT_BOOTSTRAP_ADMIN_DISPLAY_NAME"
BOOTSTRAP_ENV = (USERNAME_ENV, PASSWORD_ENV, DISPLAY_NAME_ENV)
VALID_PASSWORD = "Correct horse battery staple 2026!"


@pytest.fixture
def bootstrap_db(tmp_path, monkeypatch):
    """Give the bootstrap code a fresh SQLite database, never app settings."""
    from app.models.models import Base

    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'bootstrap.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr("app.models.SessionLocal", factory)
    for name in BOOTSTRAP_ENV:
        monkeypatch.delenv(name, raising=False)
    yield factory
    engine.dispose()


def _bootstrap():
    """Use the old entry point for the red proof, then the explicit one."""
    import app.main as main

    if hasattr(main, "_bootstrap_admin"):
        return main._bootstrap_admin()
    return main._seed_admin()


def _admins(factory):
    from app.models.models import User

    with factory() as db:
        return db.query(User).filter(User.role == "admin").all()


def _set_valid(monkeypatch, username="first.admin", display_name="First Admin"):
    monkeypatch.setenv(USERNAME_ENV, username)
    monkeypatch.setenv(PASSWORD_ENV, VALID_PASSWORD)
    if display_name is not None:
        monkeypatch.setenv(DISPLAY_NAME_ENV, display_name)


def test_fresh_database_never_receives_the_known_default(bootstrap_db):
    _bootstrap()
    assert not any(user.username == "admin" for user in _admins(bootstrap_db))


def test_no_variables_creates_no_administrator(bootstrap_db):
    _bootstrap()
    assert _admins(bootstrap_db) == []


def test_no_variables_logs_clear_bootstrap_instructions(
        bootstrap_db, caplog):
    with caplog.at_level(logging.WARNING, logger="docagent"):
        _bootstrap()
    message = caplog.text
    assert USERNAME_ENV in message
    assert PASSWORD_ENV in message
    assert "remove" in message.casefold()


def test_instructional_warning_discloses_no_password_or_hash(
        bootstrap_db, caplog):
    with caplog.at_level(logging.WARNING, logger="docagent"):
        _bootstrap()
    message = caplog.text.casefold()
    assert "admin123" not in message
    assert "password:" not in message
    assert "hash" not in message


@pytest.mark.parametrize("present,missing", [
    (USERNAME_ENV, PASSWORD_ENV),
    (PASSWORD_ENV, USERNAME_ENV),
])
def test_partial_configuration_fails_without_creating_a_user(
        bootstrap_db, monkeypatch, present, missing):
    monkeypatch.setenv(present, "partial-bootstrap-value")
    monkeypatch.delenv(missing, raising=False)
    with pytest.raises(RuntimeError, match="bootstrap"):
        _bootstrap()
    assert _admins(bootstrap_db) == []


@pytest.mark.parametrize("password", [
    "admin123",
    "change-me-in-production",
    "your_admin_password_here",
])
def test_known_default_passwords_are_rejected(
        bootstrap_db, monkeypatch, password):
    monkeypatch.setenv(USERNAME_ENV, "first.admin")
    monkeypatch.setenv(PASSWORD_ENV, password)
    with pytest.raises(RuntimeError, match="bootstrap"):
        _bootstrap()
    assert _admins(bootstrap_db) == []


def test_password_shorter_than_fifteen_characters_is_rejected(
        bootstrap_db, monkeypatch):
    monkeypatch.setenv(USERNAME_ENV, "first.admin")
    monkeypatch.setenv(PASSWORD_ENV, "short-password")
    assert len("short-password") == 14
    with pytest.raises(RuntimeError, match="bootstrap"):
        _bootstrap()
    assert _admins(bootstrap_db) == []


def test_password_equal_to_username_is_rejected_case_insensitively(
        bootstrap_db, monkeypatch):
    username = "AnAdministratorName"
    monkeypatch.setenv(USERNAME_ENV, username)
    monkeypatch.setenv(PASSWORD_ENV, username.swapcase())
    with pytest.raises(RuntimeError, match="bootstrap"):
        _bootstrap()
    assert _admins(bootstrap_db) == []


def test_valid_explicit_bootstrap_creates_exactly_one_administrator(
        bootstrap_db, monkeypatch):
    from app.core.auth import verify_password

    _set_valid(monkeypatch)
    _bootstrap()

    admins = _admins(bootstrap_db)
    assert len(admins) == 1
    admin = admins[0]
    assert admin.username == "first.admin"
    assert admin.display_name == "First Admin"
    assert admin.role == "admin"
    assert admin.client_id is None
    assert admin.is_active is True
    assert admin.password_hash != VALID_PASSWORD
    assert VALID_PASSWORD not in admin.password_hash
    assert verify_password(VALID_PASSWORD, admin.password_hash)


def test_display_name_safely_defaults_to_username(
        bootstrap_db, monkeypatch):
    _set_valid(monkeypatch, username="first.admin", display_name=None)
    _bootstrap()
    assert _admins(bootstrap_db)[0].display_name == "first.admin"


def test_existing_administrator_is_never_mutated(
        bootstrap_db, monkeypatch):
    from datetime import datetime

    from app.core.auth import hash_password
    from app.models.models import User

    existing_hash = hash_password("existing-password")
    last_login = datetime(2026, 1, 2, 3, 4, 5)
    with bootstrap_db() as db:
        db.add(User(
            username="existing.admin",
            display_name="Existing Administrator",
            email="existing@example.test",
            password_hash=existing_hash,
            role="admin",
            client_id="existing-client",
            is_active=False,
            last_login=last_login,
        ))
        db.commit()

    _set_valid(monkeypatch, username="replacement.admin",
               display_name="Replacement")
    _bootstrap()

    admins = _admins(bootstrap_db)
    assert len(admins) == 1
    admin = admins[0]
    assert admin.username == "existing.admin"
    assert admin.display_name == "Existing Administrator"
    assert admin.email == "existing@example.test"
    assert admin.password_hash == existing_hash
    assert admin.role == "admin"
    assert admin.client_id == "existing-client"
    assert admin.is_active is False
    assert admin.last_login == last_login


def test_existing_administrator_requires_no_bootstrap_variables(bootstrap_db):
    from app.core.auth import hash_password
    from app.models.models import User

    with bootstrap_db() as db:
        db.add(User(username="existing.admin", display_name="Existing",
                    password_hash=hash_password("existing-password"),
                    role="admin", is_active=True))
        db.commit()
    _bootstrap()
    assert len(_admins(bootstrap_db)) == 1


def test_repeated_startup_never_creates_a_duplicate(
        bootstrap_db, monkeypatch):
    _set_valid(monkeypatch)
    _bootstrap()
    monkeypatch.setenv(USERNAME_ENV, "different.admin")
    monkeypatch.setenv(PASSWORD_ENV, "A different valid password 2026!")
    _bootstrap()
    assert [a.username for a in _admins(bootstrap_db)] == ["first.admin"]


def test_failures_and_logs_never_disclose_supplied_password(
        bootstrap_db, monkeypatch, caplog):
    supplied = "change-me-in-production"
    monkeypatch.setenv(USERNAME_ENV, "first.admin")
    monkeypatch.setenv(PASSWORD_ENV, supplied)
    with caplog.at_level(logging.DEBUG, logger="docagent"):
        with pytest.raises(RuntimeError) as exc:
            _bootstrap()
    assert supplied not in str(exc.value)
    assert supplied not in caplog.text


def test_executable_application_code_contains_no_known_admin_password():
    app_dir = Path(bs.BACKEND_DIR) / "app"
    offenders = [
        path.relative_to(bs.BACKEND_DIR).as_posix()
        for path in app_dir.rglob("*.py")
        if "admin123" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
