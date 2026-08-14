"""Unit tests for mage.providers.probe."""

from __future__ import annotations

from mage.providers.config import ProviderConfig
from mage.providers.probe import ProbeResult, probe_provider


def _cfg(**overrides):
    base = {
        "api_key_env": "MAGIC_TEST_KEY",
        "base_url": "https://api.example.com",
        "default_model": "m",
    }
    base.update(overrides)
    return ProviderConfig.model_validate(base)


def test_probe_result_has_locked_schema():
    r = ProbeResult(
        name="x",
        base_url=None,
        default_model=None,
        config_ok=True,
        network_ok=True,
        default_model_present=None,
        models=[],
        latency_ms=10,
        error=None,
    )
    assert r.name == "x"
    assert r.network_ok is True


def test_config_fails_when_api_key_env_unset(monkeypatch):
    monkeypatch.delenv("MAGIC_TEST_KEY", raising=False)
    r = probe_provider("x", _cfg(api_key_env="MAGIC_TEST_KEY"))
    assert r.config_ok is False
    assert r.network_ok is False
    assert r.error == "$MAGIC_TEST_KEY is empty"


def test_config_fails_when_api_key_env_empty_string():
    r = probe_provider("x", _cfg(api_key_env=""))
    assert r.config_ok is False
    assert r.error == "missing api_key_env"


def test_config_fails_on_placeholder_env_value(monkeypatch):
    monkeypatch.setenv("MAGIC_TEST_KEY", "<unset>")
    r = probe_provider("x", _cfg(api_key_env="MAGIC_TEST_KEY"))
    assert r.config_ok is False
    assert "placeholder" in (r.error or "")


def test_config_fails_on_malformed_base_url(monkeypatch):
    monkeypatch.setenv("MAGIC_TEST_KEY", "real-key")
    r = probe_provider("x", _cfg(base_url="not-a-url"))
    assert r.config_ok is False
    assert "invalid base_url" in (r.error or "")
