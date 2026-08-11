"""MageTomlConfig.model_for + default_model_instance tests (P31 task 6)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from mage.host_project_config import MageTomlConfig
from mage.providers.config import ProviderConfig


@pytest.fixture
def providers(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    return {
        "anthropic": ProviderConfig(
            default_model="claude-sonnet-5-20251001",
            api_key_env="ANTHROPIC_API_KEY",
        ),
    }


class TestModelFor:
    def test_per_agent_override(self, providers):
        cfg = MageTomlConfig(
            default_model="claude-sonnet-5-20251001",
            agent_models={"inscribe": "anthropic:claude-sonnet-5-20251001"},
        )
        _model, pname, mname = cfg.model_for(
            "inscribe", providers=providers, default_provider="anthropic", env={}
        )
        assert pname == "anthropic"
        assert mname == "claude-sonnet-5-20251001"

    def test_falls_through_to_default(self, providers):
        cfg = MageTomlConfig(default_model="claude-sonnet-5-20251001")
        _model, pname, _mname = cfg.model_for(
            "inscribe", providers=providers, default_provider="anthropic", env={}
        )
        assert pname == "anthropic"

    def test_caches(self, providers):
        cfg = MageTomlConfig(default_model="claude-sonnet-5-20251001")
        # Two calls in a row return the same Model instance.
        m1, _, _ = cfg.model_for(
            "inscribe", providers=providers, default_provider="anthropic", env={}
        )
        m2, _, _ = cfg.model_for(
            "inscribe", providers=providers, default_provider="anthropic", env={}
        )
        assert m1 is m2

    def test_emits_event(self, providers):
        cfg = MageTomlConfig(default_model="claude-sonnet-5-20251001")
        events: list[tuple[str, dict]] = []

        def append(event):
            events.append((event.event_type.value, event.payload))

        from mage.orchestration.events import EventType

        sentinel = SimpleNamespace(append=append)
        cfg.model_for(
            "inscribe",
            providers=providers,
            default_provider="anthropic",
            env={},
            events_log=sentinel,
        )
        # events_log is called with Event objects; sentinel captures.
        assert any(et == EventType.PROVIDER_RESOLVED.value for et, _ in events)


class TestDefaultModelInstance:
    def test_returns_xdg_default_when_no_toml(self, providers):
        cfg = MageTomlConfig()
        _model, pname, mname = cfg.default_model_instance(
            providers=providers, default_provider="anthropic", env={}
        )
        assert pname == "anthropic"
        assert mname == "claude-sonnet-5-20251001"

    def test_emits_event_with_agent_name_none(self, providers):
        cfg = MageTomlConfig()
        events: list[tuple[str, dict]] = []

        def append(event):
            events.append((event.event_type.value, event.payload))

        from mage.orchestration.events import EventType

        sentinel = SimpleNamespace(append=append)
        cfg.default_model_instance(
            providers=providers,
            default_provider="anthropic",
            env={},
            events_log=sentinel,
        )
        assert any(
            et == EventType.PROVIDER_RESOLVED.value
            and payload.get("agent_name") is None
            for et, payload in events
        )
