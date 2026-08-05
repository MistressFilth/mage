"""Tests for host-project override mechanism."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from mage.verification.host_overrides import (
    HostConfig,
    default_check_set,
    default_host_config,
    load_host_config,
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
        config_dir = tmp_path / ".mage"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            "max_iterations: 5\ncheck_set: default\n"
        )
        config = load_host_config(tmp_path)
        assert config.max_iterations == 5

    def test_partial_config_uses_defaults_for_missing_fields(self, tmp_path: Path):
        config_dir = tmp_path / ".mage"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("max_iterations: 7\n")
        config = load_host_config(tmp_path)
        assert config.max_iterations == 7
        assert config.check_set == "default"  # default preserved

    def test_invalid_yaml_raises(self, tmp_path: Path):
        config_dir = tmp_path / ".mage"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text("not: valid: yaml: at all: :::")
        with pytest.raises(yaml.YAMLError):
            load_host_config(tmp_path)


def test_host_config_require_plan_approval_default():
    config = HostConfig()
    assert config.require_plan_approval is True


def test_host_config_require_plan_approval_overridable():
    config = HostConfig(require_plan_approval=False)
    assert config.require_plan_approval is False


def test_host_config_plan_template_path_optional():
    config = HostConfig()
    assert config.plan_template_path is None

    custom = Path("/tmp/custom-template.md")
    config2 = HostConfig(plan_template_path=custom)
    assert config2.plan_template_path == custom


def test_default_host_config_returns_default():
    config = default_host_config()
    assert isinstance(config, HostConfig)
    assert config.require_plan_approval is True


def test_host_config_max_iterations_default_is_3():
    config = HostConfig()
    assert config.max_iterations == 3


def test_host_config_max_iterations_override():
    config = HostConfig(max_iterations=5)
    assert config.max_iterations == 5


def test_host_config_enabled_reviewers_default_is_none():
    config = HostConfig()
    assert config.enabled_reviewers is None


def test_host_config_enabled_reviewers_override():
    config = HostConfig(enabled_reviewers=["spec_compliance", "testability"])
    assert config.enabled_reviewers == ["spec_compliance", "testability"]


def test_load_host_config_parses_max_iterations(tmp_path: Path):
    import yaml

    config_dir = tmp_path / ".mage"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(yaml.safe_dump({"max_iterations": 7}))
    config = load_host_config(tmp_path)
    assert config.max_iterations == 7


class TestPlan4HostConfig:
    def test_per_loop_max_iterations_default(self):
        from mage.verification.host_overrides import HostConfig

        cfg = HostConfig()
        assert cfg.per_loop_max_iterations == 8

    def test_eof_max_iterations_default(self):
        from mage.verification.host_overrides import HostConfig

        cfg = HostConfig()
        assert cfg.eof_max_iterations == 3

    def test_per_loop_max_iterations_override(self):
        from mage.verification.host_overrides import HostConfig

        cfg = HostConfig(per_loop_max_iterations=4)
        assert cfg.per_loop_max_iterations == 4

    def test_eof_max_iterations_override(self):
        from mage.verification.host_overrides import HostConfig

        cfg = HostConfig(eof_max_iterations=5)
        assert cfg.eof_max_iterations == 5


class TestPlan5SettleHostConfig:
    def test_settle_defaults(self):
        from mage.verification.host_overrides import HostConfig

        config = HostConfig()

        assert config.test_runner_command == ["uv", "run", "pytest", "-v"]
        assert config.base_branch == "main"

    def test_settle_overrides_load_from_yaml(self, tmp_path):
        import yaml

        from mage.verification.host_overrides import load_host_config

        config_dir = tmp_path / ".mage"
        config_dir.mkdir()
        (config_dir / "config.yaml").write_text(
            yaml.safe_dump(
                {
                    "test_runner_command": ["nox", "-s", "tests"],
                    "base_branch": "trunk",
                }
            )
        )

        config = load_host_config(tmp_path)

        assert config.test_runner_command == ["nox", "-s", "tests"]
        assert config.base_branch == "trunk"


def test_host_config_model_defaults_to_none():
    from mage.verification.host_overrides import HostConfig

    cfg = HostConfig(test_runner_command=["pytest"])
    assert cfg.model is None


def test_host_config_model_accepts_string():
    from mage.verification.host_overrides import HostConfig

    cfg = HostConfig(test_runner_command=["pytest"], model="openai:gpt-4o")
    assert cfg.model == "openai:gpt-4o"
