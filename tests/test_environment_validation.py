"""Startup configuration validation by ENVIRONMENT (Part 2.4)."""
import pytest

from tests.test_boot_guards import DEPLOY, REAL_KEY, _build


def test_development_and_dev_accept_the_defaults(monkeypatch):
    _build(monkeypatch, ENVIRONMENT="development")
    _build(monkeypatch, ENVIRONMENT="dev")


def test_an_unknown_environment_is_refused_without_echoing_it(monkeypatch):
    with pytest.raises(Exception) as e:
        _build(monkeypatch, ENVIRONMENT="prodd-SECRETISH")
    assert "SECRETISH" not in str(e.value)


@pytest.mark.parametrize("override,named", [
    ({"DATABASE_URL": "sqlite:///x.db"}, "DATABASE_URL"),
    ({"DATABASE_URL": "postgresql://u:TOPSECRET@localhost/db"}, "DATABASE_URL"),
    ({"S3_BUCKET": ""}, "S3_BUCKET"),
    ({"AWS_SECRET_ACCESS_KEY": ""}, "AWS_SECRET_ACCESS_KEY"),
    ({"GEMINI_API_KEY": ""}, "GEMINI_API_KEY"),
    ({"ALLOWED_ORIGINS": "*"}, "ALLOWED_ORIGINS"),
    ({"ALLOWED_ORIGINS": ""}, "ALLOWED_ORIGINS"),
    ({"TRUSTED_PROXY_COUNT": "9"}, "TRUSTED_PROXY_COUNT"),
    ({"PRIMARY_LLM": "stub"}, "stub"),
])
@pytest.mark.parametrize("env", ["staging", "production"])
def test_each_missing_or_weak_setting_is_named_never_printed(monkeypatch, override, named, env):
    with pytest.raises(Exception) as e:
        _build(monkeypatch, ENVIRONMENT=env, SECRET_KEY=REAL_KEY, **{**DEPLOY, **override})
    msg = str(e.value)
    assert named in msg and "TOPSECRET" not in msg and REAL_KEY not in msg


def test_every_problem_in_one_message(monkeypatch):
    with pytest.raises(Exception) as e:
        _build(monkeypatch, ENVIRONMENT="production", SECRET_KEY="short",
               **{**DEPLOY, "GEMINI_API_KEY": "", "ALLOWED_ORIGINS": ""})
    msg = str(e.value)
    assert all(n in msg for n in ("SECRET_KEY", "GEMINI_API_KEY", "ALLOWED_ORIGINS"))


def test_local_storage_in_production_is_warned_not_refused(monkeypatch):
    with pytest.warns(UserWarning, match="lost at every deploy"):
        _build(monkeypatch, ENVIRONMENT="production", SECRET_KEY=REAL_KEY,
               **{**DEPLOY, "STORAGE_BACKEND": "local"})
