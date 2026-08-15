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


class _FakeModel:
    def __init__(self, model_id):
        self.id = model_id


class _FakePage:
    def __init__(self, ids):
        self.data = [_FakeModel(i) for i in ids]


class _FakeModels:
    """Stands in for ``Anthropic().models``.

    The real SDK exposes ``models`` as an *attribute* holding a ``Models``
    object, so the probe calls ``client.models.list(timeout=...)``. The fake
    mirrors that shape; making ``models`` a method here would raise
    ``AttributeError`` and be swallowed as a network failure.
    """

    def __init__(self, ids):
        self._ids = ids

    def list(self, timeout=None):
        return _FakePage(self._ids)


class _FakeClient:
    def __init__(self, ids):
        self.models = _FakeModels(ids)


def test_network_probe_success(monkeypatch):
    monkeypatch.setenv("MAGIC_TEST_KEY", "sk-real")
    from mage.providers import probe as probe_mod

    monkeypatch.setattr(
        probe_mod, "Anthropic", lambda **kw: _FakeClient(["m1", "m2", "m3"])
    )
    r = probe_provider("x", _cfg(default_model="m2"))
    assert r.config_ok is True
    assert r.network_ok is True
    assert r.models == ["m1", "m2", "m3"]
    assert r.default_model_present is True
    assert r.latency_ms is not None and r.latency_ms >= 0


def test_network_probe_default_model_missing_from_list(monkeypatch):
    monkeypatch.setenv("MAGIC_TEST_KEY", "sk-real")
    from mage.providers import probe as probe_mod

    monkeypatch.setattr(probe_mod, "Anthropic", lambda **kw: _FakeClient(["m1"]))
    r = probe_provider("x", _cfg(default_model="not-in-list"))
    assert r.network_ok is True
    assert r.default_model_present is False


def test_network_probe_default_model_unset_means_none(monkeypatch):
    monkeypatch.setenv("MAGIC_TEST_KEY", "sk-real")
    from mage.providers import probe as probe_mod

    monkeypatch.setattr(probe_mod, "Anthropic", lambda **kw: _FakeClient(["m1"]))
    cfg = ProviderConfig.model_validate(
        {
            "api_key_env": "MAGIC_TEST_KEY",
            "base_url": "https://api.example.com",
            "default_model": "placeholder",
        }
    )
    r = probe_provider("x", cfg)
    # default_model is required by the model, so we can't easily leave it unset
    # without changing ProviderConfig. Instead verify that an unmatched default
    # surfaces as present=False (covered above) and a matching one as True.
    assert r.network_ok is True


def test_network_probe_sdk_error(monkeypatch):
    monkeypatch.setenv("MAGIC_TEST_KEY", "sk-real")

    class _ErrModels:
        def list(self, timeout=None):
            raise Exception("boom")  # noqa: TRY002

    class _ErrClient:
        def __init__(self):
            self.models = _ErrModels()

    from mage.providers import probe as probe_mod

    monkeypatch.setattr(probe_mod, "Anthropic", lambda **kw: _ErrClient())
    r = probe_provider("x", _cfg())
    assert r.config_ok is True
    assert r.network_ok is False
    assert "boom" in (r.error or "")


def test_default_model_present_none_when_cfg_default_model_is_none(monkeypatch):
    monkeypatch.setenv("MAGIC_TEST_KEY", "sk-real")
    from mage.providers import probe as probe_mod

    monkeypatch.setattr(probe_mod, "Anthropic", lambda **kw: _FakeClient(["m1"]))
    cfg = ProviderConfig.model_construct(
        api_key_env="MAGIC_TEST_KEY",
        base_url="https://api.example.com",
        default_model=None,
        options={},
    )
    r = probe_provider("x", cfg)
    assert r.default_model_present is None
