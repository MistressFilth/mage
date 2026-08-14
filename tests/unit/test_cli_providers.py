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
