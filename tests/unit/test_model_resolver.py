"""resolve_model precedence chain tests (P31 task 4)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic_ai.models.test import TestModel

from mage.providers.config import ProviderConfig
from mage.providers.errors import MageInvalidModelStringError
from mage.providers.resolver import resolve_model


@pytest.fixture
def providers(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test")
    return {
        "anthropic": ProviderConfig(
            default_model="claude-sonnet-5-20251001",
            api_key_env="ANTHROPIC_API_KEY",
        ),
        "minimax": ProviderConfig(
            base_url="https://api.minimax.io/anthropic",
            default_model="MiniMax-M3",
            api_key_env="MINIMAX_API_KEY",
        ),
    }


@pytest.fixture
def host_cfg():
    return SimpleNamespace(
        default_model=None,
        agent_models={},
    )


class TestPrecedenceChain:
    def test_tier1_env_per_agent(self, providers, host_cfg, monkeypatch):
        monkeypatch.setenv("MAGE_MODEL_INSCRIBE", "minimax:MiniMax-M3")
        _model, pname, mname, source = resolve_model(
            "inscribe", providers, "anthropic", host_cfg, monkeypatch
        )
        assert source == "env"
        assert pname == "minimax"
        assert mname == "MiniMax-M3"

    def test_tier2_mage_toml_per_agent(self, providers, host_cfg, monkeypatch):
        host_cfg.agent_models = {"inscribe": "minimax:MiniMax-M3"}
        _model, pname, _mname, source = resolve_model(
            "inscribe", providers, "anthropic", host_cfg, monkeypatch
        )
        assert source == "mage_toml_agent"
        assert pname == "minimax"

    def test_tier3_mage_toml_default(self, providers, host_cfg, monkeypatch):
        host_cfg.default_model = "minimax:MiniMax-M3"
        _model, pname, _mname, source = resolve_model(
            "inscribe", providers, "anthropic", host_cfg, monkeypatch
        )
        assert source == "mage_toml_default"
        assert pname == "minimax"

    def test_tier4_xdg_default(self, providers, host_cfg):
        _model, pname, mname, source = resolve_model(
            "inscribe", providers, "anthropic", host_cfg, {}
        )
        assert source == "xdg_default"
        assert pname == "anthropic"
        assert mname == "claude-sonnet-5-20251001"

    def test_tier5_test_model_fallback(self, providers, host_cfg):
        # Pass empty providers dict so XDG default lookup also fails.
        model, _pname, _mname, source = resolve_model(
            "inscribe", {}, "anthropic", host_cfg, {}
        )
        assert source == "test_model"
        assert isinstance(model, TestModel)

    def test_env_beats_mage_toml(self, providers, host_cfg, monkeypatch):
        monkeypatch.setenv("MAGE_MODEL_INSCRIBE", "anthropic:claude-sonnet-5-20251001")
        host_cfg.agent_models = {"inscribe": "minimax:MiniMax-M3"}
        _model, pname, _mname, source = resolve_model(
            "inscribe", providers, "anthropic", host_cfg, monkeypatch
        )
        assert source == "env"
        assert pname == "anthropic"


class TestModelStringParsing:
    def test_bare_string(self, providers, host_cfg):
        host_cfg.default_model = "MiniMax-M3"
        _, pname, mname, _ = resolve_model(
            "inscribe", providers, "anthropic", host_cfg, {}
        )
        # Bare resolves via default_provider (anthropic), but model_name is MiniMax-M3.
        assert pname == "anthropic"
        assert mname == "MiniMax-M3"

    def test_qualified_string(self, providers, host_cfg):
        host_cfg.default_model = "minimax:MiniMax-M3"
        _, pname, mname, _ = resolve_model(
            "inscribe", providers, "anthropic", host_cfg, {}
        )
        assert pname == "minimax"
        assert mname == "MiniMax-M3"

    def test_malformed_raises(self, providers, host_cfg):
        host_cfg.default_model = "foo:bar:baz"
        with pytest.raises(MageInvalidModelStringError):
            resolve_model("inscribe", providers, "anthropic", host_cfg, {})
