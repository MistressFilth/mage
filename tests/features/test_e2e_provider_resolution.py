"""Pipeline with MiniMax-pinned agent → AnthropicModel with right base_url."""

from __future__ import annotations

import os


def test_mage_toml_pinning_yields_minimax_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
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
    (tmp_path / "mage.toml").write_text('[agents]\ninscribe = "minimax:MiniMax-M3"\n')

    from typing import cast

    from pydantic_ai.models.anthropic import AnthropicModel

    from mage.host_project_config import load_mage_toml
    from mage.providers.config import load_xdg_providers

    providers, default = load_xdg_providers()
    mage_toml = load_mage_toml(tmp_path)
    model, pname, mname = mage_toml.model_for(
        "inscribe",
        providers=providers,
        default_provider=default,
        env=dict(os.environ),
    )
    assert pname == "minimax"
    assert mname == "MiniMax-M3"
    anthropic_model = cast(AnthropicModel, model)
    base_url = getattr(anthropic_model, "base_url", None) or getattr(
        anthropic_model.client, "base_url", None
    )
    # AnthropicProvider appends a trailing slash; normalize both sides.
    assert str(base_url).rstrip("/") == "https://api.minimax.io/anthropic"
