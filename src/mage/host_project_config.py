"""Mage.toml (host-project config) parser (P31).

Parses ``<project_root>/mage.toml`` if present; returns empty
``MageTomlConfig`` if absent.

Distinct from ``mage.verification.host_overrides.HostConfig`` which holds
verification-side host overrides.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from mage.settings import MageConfigurationError

__all__ = ["AgentName", "MageTomlConfig", "load_mage_toml"]

AgentName = Literal["inscribe", "realize", "etch", "cosmetic_refiner"]


class MageTomlConfig(BaseModel):
    """Parsed ``mage.toml`` content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_model: str | None = None
    agent_models: dict[AgentName, str] = {}
    orphan_branch: str = "feature-artifacts"


def load_mage_toml(project_root: Path) -> MageTomlConfig:
    """Load ``<project_root>/mage.toml`` if present."""
    cfg_path = Path(project_root) / "mage.toml"
    if not cfg_path.exists():
        return MageTomlConfig()
    try:
        data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise MageConfigurationError(cfg_path, str(exc)) from exc
    try:
        if "agents" in data:
            agents = dict(data.pop("agents"))
            orphan_branch = agents.pop("orphan_branch", None)
            data = {**data, "agent_models": agents}
            if orphan_branch is not None:
                data["orphan_branch"] = orphan_branch
        return MageTomlConfig.model_validate(data)
    except ValidationError as exc:
        raise MageConfigurationError(cfg_path, str(exc)) from exc
