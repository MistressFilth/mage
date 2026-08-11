"""Pipeline run with unset MiniMax key → PROVIDER_RESOLVED_FAILED + halt."""

from __future__ import annotations

import os

import pytest


def test_pipeline_with_minimax_pinned_but_key_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    # XDG config with both providers
    xdg = tmp_path / "xdg"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    (xdg / "mage").mkdir(parents=True)
    (xdg / "mage" / "config.toml").write_text(
        'default_provider = "anthropic"\n\n'
        "[providers.anthropic]\n"
        'default_model = "claude-sonnet-5-20251001"\n'
        'api_key_env = "ANTHROPIC_API_KEY"\n\n'
        "[providers.minimax]\n"
        'base_url = "https://api.minimax.io/anthropic"\n'
        'default_model = "MiniMax-M3"\n'
        'api_key_env = "MINIMAX_API_KEY"\n'
    )
    # mage.toml pins inscribe to MiniMax
    (tmp_path / "mage.toml").write_text('[agents]\ninscribe = "minimax:MiniMax-M3"\n')

    from mage.host_project_config import load_mage_toml
    from mage.providers.config import load_xdg_providers
    from mage.providers.errors import MageMissingApiKeyError

    providers, default = load_xdg_providers()
    mage_toml = load_mage_toml(tmp_path)
    with pytest.raises(MageMissingApiKeyError):
        mage_toml.model_for(
            "inscribe",
            providers=providers,
            default_provider=default,
            env=dict(os.environ),
        )
