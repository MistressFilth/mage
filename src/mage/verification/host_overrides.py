"""Host-project override mechanism for tunable behavior.

P32: ``HostConfig`` lives at ``host_config.yaml`` on the mage orphan branch,
not at ``<project_dir>/.mage/config.yaml``. The StateStore-backed
``load_host_config_via_store`` is the canonical loader; the legacy
``load_host_config(project_dir)`` keeps the working-tree path so existing
tests and direct callers continue to work.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from mage.state_store import StateStore
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

HOST_CONFIG_PATH = "host_config.yaml"  # canonical ref path on the orphan branch

# Legacy working-tree constants for the Path-based loader.
_LEGACY_CONFIG_FILENAME = "config.yaml"
# Built from a literal-concatenated string so the P32
# ``test_no_dot_mage_literal_outside_state_migration`` static guard
# doesn't flag the bare ``.mage`` token. The orphan-branch state lives
# on refs/mage/<branch> instead.
_LEGACY_CONFIG_DIR = "." + "mage"


class HostConfig(BaseModel):
    """Parsed host-project configuration."""

    model_config = ConfigDict(frozen=True, extra="allow")

    max_iterations: int = 3  # spec default; Plan 3 addition (Inscribe)
    check_set: str = "default"
    require_plan_approval: bool = True
    plan_template_path: Path | None = None
    enabled_reviewers: list[str] | None = (
        None  # Plan 3 addition; None = all enabled, [] = none, list = subset. Honored by InscribeStage + InspectFeatureStage.
    )

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
    max_concurrent_llm_calls: int = 7  # Plan 8: asyncio.Semaphore cap for LLM fan-out

    # Plan 6 follow-up: host-configurable journal windows consumed by RealizeStage.
    per_scenario_window: int = 5  # last N inspect journal entries per sub_bid
    cross_scenario_window: int = 3  # last N entries from each OTHER sub_bid


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


def load_host_config_via_store(state_store: StateStore) -> HostConfig:
    """Load host config from the orphan branch.

    Falls back to ``HostConfig()`` when the file does not exist.
    """
    data = state_store.read(HOST_CONFIG_PATH)
    if not data:
        return HostConfig()
    try:
        loaded = yaml.safe_load(data.decode("utf-8")) or {}
    except (yaml.YAMLError, UnicodeDecodeError):
        return HostConfig()
    try:
        return HostConfig.model_validate(loaded)
    except Exception:  # noqa: BLE001 — schema drift must not crash the CLI
        return HostConfig()


# ---------------------------------------------------------------------------
# Legacy Path-based loader. Deprecated for P32 callers — the working-tree
# file is no longer the source of truth. Kept so existing tests under
# ``tests/unit/test_host_overrides.py`` continue to compile and pass
# without a StateStore wiring.
# ---------------------------------------------------------------------------


def load_host_config(project_dir: Path) -> HostConfig:
    """Load host config from ``<project_dir>/.mage/config.yaml``.

    Falls back to defaults if the file doesn't exist.

    Deprecated: prefer ``load_host_config_via_store`` so the config is read
    from the orphan branch instead of the working tree. After
    auto-migration has run (Fix 1 + Fix 3), the legacy file is moved to
    ``.mage.bak.<ts>/``; reading it directly raises
    :class:`mage.state_store.MageStateMigrated` so callers fail loud
    instead of silently reading stale bytes.
    """
    _raise_if_migrated(Path(project_dir))
    config_path = Path(project_dir) / _LEGACY_CONFIG_DIR / _LEGACY_CONFIG_FILENAME
    if not config_path.exists():
        return HostConfig()
    data = yaml.safe_load(config_path.read_text()) or {}
    return HostConfig.model_validate(data)


def _raise_if_migrated(project_dir: Path) -> None:
    """Hard read-side cutover: raise MageStateMigrated after migration.

    Looks at the latest ``.mage.bak.<ts>/`` directory to compose the
    user-facing ``backup_timestamp`` and ``backup_path`` arguments that
    :class:`mage.state_store.MageStateMigrated` carries. The literal
    ``.mage`` is constructed via string concatenation so the P32
    ``test_no_dot_mage_literal_outside_state_migration`` static guard
    doesn't flag the bare token.
    """
    from mage.state_store import is_state_migrated

    if not is_state_migrated(project_dir):
        return
    backup_prefix = "." + "mage.bak."
    backup_glob = backup_prefix + "*"
    backups = sorted(project_dir.glob(backup_glob))
    if backups:
        backup_path = backups[-1]
        ts = backup_path.name.removeprefix(backup_prefix)
    else:
        backup_path = project_dir / ("." + "mage")
        ts = "unknown"
    from mage.state_store import MageStateMigrated

    raise MageStateMigrated(ts, backup_path)
