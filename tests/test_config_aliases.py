"""
Config variables must be read under the names production actually sets.

The audit's central finding was a whole class of bug where a setting is
declared under one name and set under another: pydantic's extra="ignore"
swallows the mismatch, so the variable looks configured and does nothing.
CORS_ORIGINS and MAX_FILE_SIZE_MB were both instances. These tests pin the
aliases and — just as important — pin that a malformed value cannot stop the
service booting.
"""
import importlib

import pytest

from tests.harness import bootstrap as bs

bs.bootstrap()


def _build(monkeypatch, **env):
    import app.config as cfg
    for k in ("ALLOWED_ORIGINS", "CORS_ORIGINS",
              "MAX_UPLOAD_SIZE_MB", "MAX_FILE_SIZE_MB"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    importlib.reload(cfg)
    return cfg.Settings(_env_file=None)


class TestCorsOrigins:
    def test_the_name_production_actually_sets_is_read(self, monkeypatch):
        s = _build(monkeypatch, CORS_ORIGINS="https://app.example.com")
        assert s.cors_origins == ["https://app.example.com"]

    def test_the_declared_name_still_works(self, monkeypatch):
        s = _build(monkeypatch, ALLOWED_ORIGINS="https://a.example.com")
        assert s.cors_origins == ["https://a.example.com"]

    def test_comma_separated(self, monkeypatch):
        s = _build(monkeypatch,
                   CORS_ORIGINS="https://a.example.com, https://b.example.com")
        assert s.cors_origins == ["https://a.example.com",
                                     "https://b.example.com"]

    def test_json_list(self, monkeypatch):
        s = _build(monkeypatch,
                   CORS_ORIGINS='["https://a.example.com","https://b.example.com"]')
        assert s.cors_origins == ["https://a.example.com",
                                     "https://b.example.com"]

    def test_unset_falls_back_to_permissive_default(self, monkeypatch):
        assert _build(monkeypatch).cors_origins == ["*"]

    @pytest.mark.parametrize("bad", ["", "   ", "[", "[not json", "[]", ","])
    def test_a_malformed_value_never_stops_the_service_booting(self, monkeypatch, bad):
        """A bad CORS value must degrade, not crash. Crashing on boot over a
        misconfigured origin list would be a worse failure than the bug."""
        s = _build(monkeypatch, CORS_ORIGINS=bad)
        assert isinstance(s.cors_origins, list)
        assert s.cors_origins  # never empty


class TestUploadLimit:
    def test_the_name_production_actually_sets_is_read(self, monkeypatch):
        s = _build(monkeypatch, MAX_FILE_SIZE_MB="25")
        assert s.MAX_UPLOAD_SIZE_MB == 25
        assert s.max_upload_bytes == 25 * 1024 * 1024

    def test_the_declared_name_still_works(self, monkeypatch):
        assert _build(monkeypatch, MAX_UPLOAD_SIZE_MB="10").MAX_UPLOAD_SIZE_MB == 10

    def test_default_unchanged_when_neither_is_set(self, monkeypatch):
        assert _build(monkeypatch).MAX_UPLOAD_SIZE_MB == 50

    def test_changing_the_railway_value_now_actually_changes_the_limit(
            self, monkeypatch):
        """The symptom of the original bug was that both happened to be 50, so
        nothing looked wrong. A different value must now take effect."""
        assert _build(monkeypatch, MAX_FILE_SIZE_MB="7").max_upload_bytes == \
            7 * 1024 * 1024
