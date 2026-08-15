"""Unit tests for mage.cli_providers formatters."""

from __future__ import annotations

import json

from mage.cli_providers import _format_human, _format_json
from mage.providers.probe import ProbeResult


def _r(**overrides):
    base = {
        "name": "minimax",
        "base_url": "https://api.minimax.io/anthropic",
        "default_model": "MiniMax-M3",
        "config_ok": True,
        "network_ok": True,
        "default_model_present": True,
        "models": ["MiniMax-M3", "m2"],
        "latency_ms": 312,
        "error": None,
    }
    base.update(overrides)
    return ProbeResult.model_validate(base)


def test_human_glyph_ok():
    out = _format_human([_r()])
    assert "✓" in out
    assert "minimax" in out
    assert "MiniMax-M3 present" in out
    assert "1 ok, 0 failed" in out


def test_human_glyph_warn_when_default_missing():
    out = _format_human([_r(default_model_present=False)])
    assert "⚠" in out
    assert "missing" in out


def test_human_glyph_fail_on_network_error():
    out = _format_human(
        [
            _r(
                network_ok=False,
                default_model_present=None,
                error="401 Unauthorized",
                latency_ms=None,
                models=[],
            )
        ]
    )
    assert "✗" in out
    assert "401 Unauthorized" in out
    assert "0 ok, 1 failed" in out


def test_json_envelope_ok_flag_aggregates():
    out = _format_json(
        [
            _r(),
            _r(
                name="anthropic",
                network_ok=False,
                error="boom",
                latency_ms=None,
                default_model_present=None,
                models=[],
            ),
        ]
    )
    assert out["ok"] is False
    payload = json.dumps(out)  # must serialize
    parsed = json.loads(payload)
    assert parsed["ok"] is False
    assert len(parsed["providers"]) == 2
    assert parsed["providers"][1]["name"] == "anthropic"


def test_json_envelope_ok_true_when_all_green():
    out = _format_json([_r(), _r(name="anthropic")])
    assert out["ok"] is True


def test_default_model_present_false_does_not_flip_ok():
    out = _format_json([_r(default_model_present=False)])
    assert out["ok"] is True


from unittest.mock import patch

from mage.cli_providers import test_providers
from mage.providers.config import ProviderConfig


def test_test_providers_prints_json_and_returns_zero_when_all_ok(capsys, monkeypatch):
    monkeypatch.setenv("MAGIC_KEY", "x")
    providers = {
        "alpha": ProviderConfig.model_construct(
            api_key_env="MAGIC_KEY", base_url=None, default_model=None, options={}
        ),
    }
    fake_result = _r(
        name="alpha",
        base_url=None,
        default_model=None,
        default_model_present=None,
        models=[],
    )
    with (
        patch(
            "mage.cli_providers.load_xdg_providers", return_value=(providers, "alpha")
        ),
        patch("mage.cli_providers.probe_provider", return_value=fake_result),
    ):
        rc = test_providers("json")
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["ok"] is True


def test_test_providers_returns_one_when_any_network_fails(capsys, monkeypatch):
    monkeypatch.setenv("MAGIC_KEY", "x")
    providers = {
        "alpha": ProviderConfig.model_construct(
            api_key_env="MAGIC_KEY", base_url=None, default_model=None, options={}
        ),
        "beta": ProviderConfig.model_construct(
            api_key_env="MAGIC_KEY", base_url=None, default_model=None, options={}
        ),
    }
    fake_ok = _r(
        name="alpha",
        base_url=None,
        default_model=None,
        default_model_present=None,
        models=[],
    )
    fake_bad = _r(
        name="beta",
        base_url=None,
        default_model=None,
        default_model_present=None,
        models=[],
        network_ok=False,
        error="boom",
        latency_ms=None,
    )
    with (
        patch(
            "mage.cli_providers.load_xdg_providers", return_value=(providers, "alpha")
        ),
        patch("mage.cli_providers.probe_provider", side_effect=[fake_ok, fake_bad]),
    ):
        rc = test_providers("human")
    assert rc == 1
    out = capsys.readouterr().out
    assert "alpha" in out and "beta" in out
    assert "1 ok, 1 failed" in out


def test_test_providers_iterates_in_sorted_order(capsys, monkeypatch):
    monkeypatch.setenv("MAGIC_KEY", "x")
    providers = {
        "zeta": ProviderConfig.model_construct(
            api_key_env="MAGIC_KEY", base_url=None, default_model=None, options={}
        ),
        "alpha": ProviderConfig.model_construct(
            api_key_env="MAGIC_KEY", base_url=None, default_model=None, options={}
        ),
    }
    calls: list[str] = []

    def _probe(name, cfg):
        calls.append(name)
        return _r(
            name=name,
            base_url=None,
            default_model=None,
            default_model_present=None,
            models=[],
        )

    with (
        patch(
            "mage.cli_providers.load_xdg_providers", return_value=(providers, "alpha")
        ),
        patch("mage.cli_providers.probe_provider", side_effect=_probe),
    ):
        test_providers("human")
    assert calls == ["alpha", "zeta"]


def test_test_providers_rejects_unknown_format():
    import pytest

    with pytest.raises(ValueError):
        test_providers("xml")
