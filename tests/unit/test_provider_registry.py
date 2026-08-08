"""build_model factory tests (P31 task 3)."""

from __future__ import annotations

import pytest

from mage.providers.config import ProviderConfig
from mage.providers.errors import MageUnknownProviderError
from mage.providers.registry import (
    KNOWN_PROVIDERS,
    build_model,
    register_provider,
)


class TestKnownProviders:
    def test_pinned_set(self):
        assert KNOWN_PROVIDERS == frozenset({"anthropic", "minimax"})


class TestBuildModel:
    def test_anthropic_no_base_url(self, monkeypatch):
        # Drop ANTHROPIC_BASE_URL so the SDK default (api.anthropic.com) wins.
        monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
        provider = ProviderConfig(
            default_model="claude-sonnet-5-20251001",
            api_key_env="ANTHROPIC_API_KEY",
        )
        model = build_model("anthropic", provider, "claude-sonnet-5-20251001")
        # Pydantic-AI AnthropicModel exposes base_url via .client.base_url
        # or .base_url depending on version. Both are acceptable.
        client = getattr(model, "client", None)
        base_url = getattr(model, "base_url", None) or getattr(client, "base_url", None)
        # The anthropic SDK appends a trailing slash; "in" is the stable check.
        assert "api.anthropic.com" in str(base_url)

    def test_minimax_sets_base_url(self, monkeypatch):
        monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test")
        provider = ProviderConfig(
            base_url="https://api.minimax.io/anthropic",
            default_model="MiniMax-M3",
            api_key_env="MINIMAX_API_KEY",
        )
        model = build_model("minimax", provider, "MiniMax-M3")
        client = getattr(model, "client", None)
        base_url = getattr(model, "base_url", None) or getattr(client, "base_url", None)
        # The anthropic SDK normalizes to a trailing slash; compare roots.
        assert str(base_url).rstrip("/") == "https://api.minimax.io/anthropic"

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setenv("GROK_API_KEY", "grok-test")
        provider = ProviderConfig(default_model="grok-1", api_key_env="GROK_API_KEY")
        with pytest.raises(MageUnknownProviderError):
            build_model("grok", provider, "grok-1")

    def test_register_provider_extension(self, monkeypatch):
        """register_provider lets users add a new provider at runtime."""
        monkeypatch.setenv("GROK_API_KEY", "grok-test")

        def grok_factory(p, model_name):
            from pydantic_ai.models.openai import OpenAIChatModel
            from pydantic_ai.providers.openai import OpenAIProvider

            return OpenAIChatModel(
                model_name, provider=OpenAIProvider(api_key="ignored")
            )

        register_provider("grok", grok_factory)
        provider = ProviderConfig(default_model="grok-1", api_key_env="GROK_API_KEY")
        # Should not raise now that grok is registered.
        model = build_model("grok", provider, "grok-1")
        assert model is not None
