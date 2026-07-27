"""Tests for host-project override mechanism."""

from __future__ import annotations

from pathlib import Path

import pytest
from mage.verification.host_overrides import (
    HostConfig,
    default_check_set,
    load_host_config,
)
from mage.verification.mechanical import (
    CrossBehaviorTagsValidCheck,
    GherkinSyntaxCheck,
    LifecycleStatusTagPresentCheck,
    ScenarioNameUniqueCheck,
    StepDefinitionsResolvableCheck,
    SubBidAssignedCheck,
    TagsRegisteredCheck,
)


class TestDefaultCheckSet:
    def test_returns_all_seven_default_checks(self):
        checks = default_check_set(registered_tags=set(), step_patterns=[])
        names = {type(c).__name__ for c in checks}
        assert names == {
            "GherkinSyntaxCheck",
            "ScenarioNameUniqueCheck",
            "TagsRegisteredCheck",
            "StepDefinitionsResolvableCheck",
            "LifecycleStatusTagPresentCheck",
            "SubBidAssignedCheck",
            "CrossBehaviorTagsValidCheck",
        }


class TestLoadHostConfig:
    def test_no_config_file_returns_defaults(self, tmp_path: Path):
        config = load_host_config(tmp_path)
        assert config.max_iterations == 3
        assert config.check_set == "default"

    def test_loads_config_from_yaml(self, tmp_path: Path):
        config_dir = tmp_path / ".haileris"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "max_iterations: 5\ncheck_set: default\n"
        )
        config = load_host_config(tmp_path)
        assert config.max_iterations == 5

    def test_partial_config_uses_defaults_for_missing_fields(self, tmp_path: Path):
        config_dir = tmp_path / ".haileris"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("max_iterations: 7\n")
        config = load_host_config(tmp_path)
        assert config.max_iterations == 7
        assert config.check_set == "default"  # default preserved

    def test_invalid_yaml_raises(self, tmp_path: Path):
        config_dir = tmp_path / ".haileris"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("not: valid: yaml: at all: :::")
        with pytest.raises(Exception):
            load_host_config(tmp_path)
