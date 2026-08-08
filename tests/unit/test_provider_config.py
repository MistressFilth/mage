"""ProviderConfig model + XDG loader tests (P31 task 2)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mage.providers.config import (
    ProviderConfig,
    load_xdg_providers,
)
from mage.providers.errors import MageProviderError


class TestProviderConfig:
    def test_minimal_valid(self):
        cfg = ProviderConfig(default_model="MiniMax-M3", api_key_env="MINIMAX_API_KEY")
        assert cfg.base_url is None
        assert cfg.default_model == "MiniMax-M3"
        assert cfg.api_key_env == "MINIMAX_API_KEY"
        assert cfg.options == {}

    def test_full_valid(self):
        cfg = ProviderConfig(
            base_url="https://api.minimax.io/anthropic",
            default_model="MiniMax-M3",
            api_key_env="MINIMAX_API_KEY",
            options={"region": "us"},
        )
        assert cfg.base_url == "https://api.minimax.io/anthropic"
        assert cfg.options == {"region": "us"}

    def test_rejects_unknown_field(self):
        with pytest.raises(Exception):  # pydantic ValidationError
            ProviderConfig(
                default_model="x", api_key_env="MINIMAX_API_KEY", unknown_field=1
            )

    def test_requires_default_model(self):
        with pytest.raises(Exception):
            ProviderConfig(api_key_env="MINIMAX_API_KEY")

    def test_requires_api_key_env(self):
        with pytest.raises(Exception):
            ProviderConfig(default_model="MiniMax-M3")


class TestLoadXdgProviders:
    def test_loads_full_config(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(
            textwrap.dedent(
                """\
                default_provider = "anthropic"

                [providers.anthropic]
                default_model = "claude-sonnet-5-20251001"
                api_key_env = "ANTHROPIC_API_KEY"

                [providers.minimax]
                base_url = "https://api.minimax.io/anthropic"
                default_model = "MiniMax-M3"
                api_key_env = "MINIMAX_API_KEY"
                """
            )
        )
        # The loader takes the path explicitly (test mode).
        providers, default = load_xdg_providers(path=cfg_file)
        assert default == "anthropic"
        assert set(providers) == {"anthropic", "minimax"}
        assert providers["minimax"].base_url == "https://api.minimax.io/anthropic"
        assert providers["anthropic"].default_model == "claude-sonnet-5-20251001"

    def test_missing_file_returns_empty(self, tmp_path):
        providers, default = load_xdg_providers(path=tmp_path / "absent.toml")
        assert providers == {}
        assert default == "anthropic"  # single-provider default

    def test_unknown_field_in_provider_block_fails(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(
            textwrap.dedent(
                """\
                default_provider = "anthropic"

                [providers.anthropic]
                default_model = "x"
                api_key_env = "ANTHROPIC_API_KEY"
                mystery_field = "y"
                """
            )
        )
        with pytest.raises(Exception):
            load_xdg_providers(path=cfg_file)

    def test_default_provider_not_in_table_fails(self, tmp_path):
        cfg_file = tmp_path / "config.toml"
        cfg_file.write_text(
            textwrap.dedent(
                """\
                default_provider = "grok"

                [providers.anthropic]
                default_model = "x"
                api_key_env = "ANTHROPIC_API_KEY"
                """
            )
        )
        with pytest.raises(MageProviderError):
            load_xdg_providers(path=cfg_file)
