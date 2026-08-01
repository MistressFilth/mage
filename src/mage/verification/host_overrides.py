"""Host-project override mechanism for tunable behavior."""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from mage.verification.mechanical import (
    CrossBehaviorTagsValidCheck,
    GherkinSyntaxCheck,
    LifecycleStatusTagPresentCheck,
    MechanicalCheck,
    ScenarioNameUniqueCheck,
    StepDefinitionsResolvableCheck,
    SubBidAssignedCheck,
    TagsRegisteredCheck,
)


class HostConfig(BaseModel):
    """Parsed host-project configuration."""

    model_config = ConfigDict(frozen=True, extra="allow")

    max_iterations: int = 3  # spec default; Plan 3 addition (Inscribe)
    check_set: str = "default"
    require_plan_approval: bool = True
    plan_template_path: Path | None = None
    enabled_reviewers: list[str] | None = None  # Plan 3 addition; None = all enabled, [] = none, list = subset. Honored by InscribeStage + InspectFeatureStage.

    # Plan 4 — Inner TDD loop iteration budgets
    per_loop_max_iterations: int = (
        8  # per scenario, shared by Realize + per-loop Inspect
    )
    eof_max_iterations: int = 3  # per feature, end-of-feature Inspect fix-wave (Plan 5)

    # Plan 5 — Settle finalization
    test_runner_command: list[str] = Field(
        default_factory=lambda: ["uv", "run", "pytest", "-v"]
    )
    base_branch: str = "main"
    model: str | None = (
        None  # Plan 6: agent model identifier; None = pydantic-ai default
    )
    max_concurrent_llm_calls: int = 7  # Plan 8: asyncio.Semaphore cap for LLM fan-out


def default_check_set(
    registered_tags: set[str],
    step_patterns: list[re.Pattern[str]],
) -> list[MechanicalCheck]:
    """Return the default 7 mechanical checks with the given registry state."""
    return [
        GherkinSyntaxCheck(),
        ScenarioNameUniqueCheck(),
        TagsRegisteredCheck(registered_tags=registered_tags),
        StepDefinitionsResolvableCheck(registered_patterns=step_patterns),
        LifecycleStatusTagPresentCheck(),
        SubBidAssignedCheck(),
        CrossBehaviorTagsValidCheck(),
    ]


def default_host_config() -> HostConfig:
    """Return the default host config."""
    return HostConfig()


def load_host_config(project_dir: Path) -> HostConfig:
    """Load host config from `<project_dir>/.haileris/config.yaml`.

    Falls back to defaults if the file doesn't exist.
    """
    config_path = Path(project_dir) / ".haileris" / "config.yaml"
    if not config_path.exists():
        return HostConfig()
    data = yaml.safe_load(config_path.read_text()) or {}
    return HostConfig.model_validate(data)
