"""
A production deployment must not boot on a signing key that is in this repo.

SECRET_KEY signs every JWT. It carries a default so a fresh checkout runs, and
that default is published here — so a production deploy that forgets the
variable signs tokens with a key anyone can read, and anyone can then mint an
admin token for any tenant. Nothing about the running app would look wrong:
logins work, tokens verify, the logs are clean.

The guard fires at import and only when ENVIRONMENT=production, so development
and tests keep the convenience of a default.
"""
import importlib

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()

REAL_KEY = "9f2c1d7a4b6e8035fa1c9d2e7b40build6a5c8e1f0d3b7a9c2e4f6081d3a5c7e9"
SHIPPED_DEFAULT = "change-me-in-production-use-openssl-rand-hex-32"
EXAMPLE_DEFAULT = "change-me-use-openssl-rand-hex-32"


def _build(monkeypatch, **env):
    import app.config as cfg
    for k in ("SECRET_KEY", "ENVIRONMENT"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    importlib.reload(cfg)
    return cfg.Settings(_env_file=None)


class TestProductionRefusesAPublishedKey:
    def test_the_default_in_config_py_is_refused(self, monkeypatch):
        with pytest.raises(Exception) as e:
            _build(monkeypatch, ENVIRONMENT="production",
                   SECRET_KEY=SHIPPED_DEFAULT)
        assert "SECRET_KEY" in str(e.value)

    def test_the_different_default_in_env_example_is_also_refused(self, monkeypatch):
        """config.py and .env.example ship DIFFERENT placeholders. A guard
        that only knows one of them has a hole exactly the size of the other."""
        with pytest.raises(Exception) as e:
            _build(monkeypatch, ENVIRONMENT="production",
                   SECRET_KEY=EXAMPLE_DEFAULT)
        assert "SECRET_KEY" in str(e.value)

    def test_a_missing_key_is_refused(self, monkeypatch):
        """Unset means the default applies, which is the published one."""
        with pytest.raises(Exception):
            _build(monkeypatch, ENVIRONMENT="production")

    def test_an_empty_or_whitespace_key_is_refused(self, monkeypatch):
        for bad in ("", "   ", "\t"):
            with pytest.raises(Exception):
                _build(monkeypatch, ENVIRONMENT="production", SECRET_KEY=bad)

    def test_any_change_me_variant_is_refused(self, monkeypatch):
        """Someone editing the placeholder without replacing it — the most
        likely way this goes wrong in practice."""
        for bad in ("CHANGE-ME-please", "changeme", "change-me-later-2026"):
            with pytest.raises(Exception):
                _build(monkeypatch, ENVIRONMENT="production", SECRET_KEY=bad)

    def test_the_error_says_how_to_fix_it(self, monkeypatch):
        with pytest.raises(Exception) as e:
            _build(monkeypatch, ENVIRONMENT="production",
                   SECRET_KEY=SHIPPED_DEFAULT)
        msg = str(e.value)
        assert "openssl rand -hex 32" in msg
        assert "production" in msg


class TestItDoesNotBlockLegitimateBoots:
    def test_a_real_key_boots_production(self, monkeypatch):
        s = _build(monkeypatch, ENVIRONMENT="production", SECRET_KEY=REAL_KEY)
        assert s.is_production and s.SECRET_KEY == REAL_KEY

    def test_development_still_boots_on_the_default(self, monkeypatch):
        """The default exists so a fresh checkout runs. That must keep working
        — a guard that breaks local setup gets disabled, not fixed."""
        s = _build(monkeypatch, ENVIRONMENT="development")
        assert s.SECRET_KEY == SHIPPED_DEFAULT

    def test_staging_is_not_production(self, monkeypatch):
        s = _build(monkeypatch, ENVIRONMENT="staging",
                   SECRET_KEY=SHIPPED_DEFAULT)
        assert not s.is_production


class TestWeakButSecretKeysWarnRatherThanRefuse:
    def test_a_short_real_key_boots_with_a_warning(self, monkeypatch):
        """Refusing a short key could take down a deployment that is currently
        working and whose key is genuinely secret. That is a worse outcome than
        the weakness it prevents, so this warns instead."""
        with pytest.warns(UserWarning, match="32"):
            s = _build(monkeypatch, ENVIRONMENT="production",
                       SECRET_KEY="s3cr3t-but-short")
        assert s.SECRET_KEY == "s3cr3t-but-short"

    def test_a_long_key_warns_about_nothing(self, monkeypatch):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            _build(monkeypatch, ENVIRONMENT="production", SECRET_KEY=REAL_KEY)
