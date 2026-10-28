"""Review-3 F8: ENVIRONMENT has one spelling, decided once.

`Production` and ` production ` passed the strict start-up checks (which
normalised their own copy) while `is_production` and the HSTS header compared
the raw string — so production-only behaviour could be skipped on a
deployment validated as production. The value is now normalised in a field
validator and stored normalised; unknown values refuse to start, and unset or
empty refuses on a hosting platform.
"""
import pytest

from tests.test_boot_guards import DEPLOY, REAL_KEY, _build


def _prod(monkeypatch, value):
    return _build(monkeypatch, ENVIRONMENT=value, SECRET_KEY=REAL_KEY, **DEPLOY)


@pytest.mark.parametrize("value", ["production", "Production", "PRODUCTION",
                                   " production ", "\tproduction\n", "prod", " PROD "])
def test_every_spelling_of_production_is_production(monkeypatch, value):
    s = _prod(monkeypatch, value)
    assert s.ENVIRONMENT == "production" and s.is_production


@pytest.mark.parametrize("value", ["Staging", " staging "])
def test_staging_is_normalised_and_strict(monkeypatch, value):
    assert _prod(monkeypatch, value).ENVIRONMENT == "staging"
    with pytest.raises(Exception) as e:
        _build(monkeypatch, ENVIRONMENT=value, SECRET_KEY="short", **DEPLOY)
    assert "SECRET_KEY" in str(e.value)


@pytest.mark.parametrize("value", ["Production", " production ", "prod"])
def test_a_differently_spelt_production_still_refuses_a_shipped_key(monkeypatch, value):
    with pytest.raises(Exception) as e:
        _build(monkeypatch, ENVIRONMENT=value,
               SECRET_KEY="change-me-in-production-use-openssl-rand-hex-32", **DEPLOY)
    assert "SECRET_KEY" in str(e.value)


@pytest.mark.parametrize("value", ["Dev", " DEVELOPMENT ", "dev"])
def test_development_spellings(monkeypatch, value):
    s = _build(monkeypatch, ENVIRONMENT=value)
    assert s.ENVIRONMENT == "development" and not s.is_production


@pytest.mark.parametrize("value", ["producton", "live", "qa", "prod-eu"])
def test_an_unknown_value_refuses_to_start(monkeypatch, value):
    with pytest.raises(Exception) as e:
        _build(monkeypatch, ENVIRONMENT=value)
    assert "ENVIRONMENT must be" in str(e.value) and value not in str(e.value)


@pytest.mark.parametrize("value", [None, "", "   "])
def test_unset_or_empty_is_development_on_a_workstation(monkeypatch, value):
    for m in ("RAILWAY_ENVIRONMENT", "RAILWAY_PROJECT_ID", "RAILWAY_SERVICE_ID",
              "RENDER", "FLY_APP_NAME", "DYNO", "K_SERVICE"):
        monkeypatch.delenv(m, raising=False)
    s = _build(monkeypatch) if value is None else _build(monkeypatch, ENVIRONMENT=value)
    assert s.ENVIRONMENT == "development"


@pytest.mark.parametrize("value", [None, "", "  "])
@pytest.mark.parametrize("marker", ["RAILWAY_ENVIRONMENT", "RENDER", "K_SERVICE"])
def test_unset_or_empty_refuses_on_a_hosting_platform(monkeypatch, value, marker):
    monkeypatch.setenv(marker, "production")
    with pytest.raises(Exception) as e:
        _build(monkeypatch) if value is None else _build(monkeypatch, ENVIRONMENT=value)
    assert "ENVIRONMENT is not set" in str(e.value) and marker in str(e.value)


def test_hsts_follows_the_normalised_value(monkeypatch):
    """The header is the production-only behaviour the raw comparison
    skipped: a settings object built from `Production` must send it."""
    from fastapi.testclient import TestClient
    import app.config as cfg
    import app.main as main
    s = _prod(monkeypatch, " Production ")
    monkeypatch.setattr(cfg, "settings", s)
    monkeypatch.setattr(main, "settings", s)
    # No `with`: the lifespan (migrations, boot jobs) must not run here.
    r = TestClient(main.create_app()).get("/health", headers={"x-forwarded-proto": "https"})
    assert "Strict-Transport-Security" in r.headers
