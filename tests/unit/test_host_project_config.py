"""MageTomlConfig + load_mage_toml tests (P31 task 5)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import get_args

import pytest
from pydantic import ValidationError

from mage.host_project_config import AgentName, MageTomlConfig, load_mage_toml
from mage.settings import MageConfigurationError


class TestMageTomlConfig:
    def test_empty(self):
        cfg = MageTomlConfig()
        assert cfg.default_model is None
        assert cfg.agent_models == {}
        assert cfg.orphan_branch == "feature-artifacts"

    def test_full(self):
        cfg = MageTomlConfig(
            default_model="claude-sonnet-5-20251001",
            agent_models={"inscribe": "minimax:MiniMax-M3"},
            orphan_branch="my-artifacts",
        )
        assert cfg.default_model == "claude-sonnet-5-20251001"
        assert cfg.agent_models == {"inscribe": "minimax:MiniMax-M3"}
        assert cfg.orphan_branch == "my-artifacts"

    def test_rejects_unknown_agent(self):
        with pytest.raises(ValidationError):
            MageTomlConfig.model_validate({"agent_models": {"grok": "x"}})

    def test_rejects_unknown_top_level_field(self):
        with pytest.raises(ValidationError):
            MageTomlConfig.model_validate({"mystery_field": "x"})


class TestLoadMageToml:
    def test_missing_returns_empty(self, tmp_path: Path):
        assert load_mage_toml(tmp_path) == MageTomlConfig()

    def test_loads_full(self, tmp_path: Path):
        (tmp_path / "mage.toml").write_text(
            textwrap.dedent("""\
            default_model = "claude-sonnet-5-20251001"

            [agents]
            inscribe = "minimax:MiniMax-M3"
            realize = "minimax:MiniMax-M3"
            etch = "anthropic:claude-sonnet-5-20251001"

            orphan_branch = "feature-artifacts"
            """)
        )
        cfg = load_mage_toml(tmp_path)
        assert cfg.default_model == "claude-sonnet-5-20251001"
        assert cfg.agent_models["inscribe"] == "minimax:MiniMax-M3"
        assert cfg.orphan_branch == "feature-artifacts"

    def test_unknown_agent_in_file_fails(self, tmp_path: Path):
        (tmp_path / "mage.toml").write_text('[agents]\ngrok = "x"\n')
        with pytest.raises(MageConfigurationError):
            load_mage_toml(tmp_path)

    def test_unknown_top_level_field_fails(self, tmp_path: Path):
        (tmp_path / "mage.toml").write_text('default_model = "x"\nmystery = 1\n')
        with pytest.raises(MageConfigurationError):
            load_mage_toml(tmp_path)

    def test_malformed_toml_fails(self, tmp_path: Path):
        (tmp_path / "mage.toml").write_text("not = valid = toml")
        with pytest.raises(MageConfigurationError):
            load_mage_toml(tmp_path)


class TestAgentNameLiteral:
    def test_pinned_set(self):
        assert set(get_args(AgentName)) == {
            "inscribe",
            "realize",
            "etch",
            "cosmetic_refiner",
        }
