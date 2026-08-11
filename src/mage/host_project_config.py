"""mage.toml (host-project config) parser + resolver (P31)."""

from __future__ import annotations

import tomllib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, PrivateAttr, ValidationError
from pydantic_ai.models import Model

from mage.providers.resolver import resolve_model
from mage.settings import MageConfigurationError

__all__ = [
    "AgentName",
    "MageTomlConfig",
    "load_mage_toml",
    "resolve_model_logged",
]

AgentName = Literal["inscribe", "realize", "etch", "cosmetic_refiner"]


class MageTomlConfig(BaseModel):
    """Parsed ``mage.toml`` content + per-agent resolver."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    default_model: str | None = None
    agent_models: dict[AgentName, str] = {}
    orphan_branch: str = "feature-artifacts"  # placeholder; P32 owns

    # Resolved-model cache, keyed by agent_name (or "__default__"). PrivateAttr
    # keeps it out of model_fields and works cleanly with frozen=True.
    _resolved: dict[str, tuple[Model, str, str]] = PrivateAttr(default_factory=dict)

    def model_for(
        self,
        agent_name: AgentName,
        *,
        providers: dict[str, Any],
        default_provider: str,
        env: dict[str, str],
        events_log: Any | None = None,
    ) -> tuple[Model, str, str]:
        """Resolve the model for ``agent_name`` (5-tier chain).

        Returns ``(model, provider_name, model_name)``. Caches the result.
        Emits ``PROVIDER_RESOLVED`` when ``events_log`` provided.
        ``PROVIDER_RESOLVED_FAILED`` is appended to ``events_log`` (sync) before
        any resolution failure is raised.
        """
        if agent_name in self._resolved:
            return self._resolved[agent_name]
        model, pname, mname, source = resolve_model(
            agent_name,
            providers,
            default_provider,
            self,
            env,
            events_log=events_log,
        )
        if events_log is not None and source != "test_model":
            from mage.orchestration.events import Event, EventType

            events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.PROVIDER_RESOLVED,
                    payload={
                        "agent_name": agent_name,
                        "provider": pname,
                        "model_name": mname,
                        "source": source,
                    },
                )
            )
        result = (model, pname, mname)
        # PrivateAttr dict mutation persists across calls (no `or {}` fallback —
        # an empty dict is falsy and would yield a throwaway on every call).
        self._resolved[agent_name] = result
        return result

    def default_model_instance(
        self,
        *,
        providers: dict[str, Any],
        default_provider: str,
        env: dict[str, str],
        events_log: Any | None = None,
    ) -> tuple[Model, str, str]:
        """Resolve the default-tier model (tiers 3-4 only).

        Used by the reviewer registry where no per-reviewer override
        exists. ``agent_name=None`` in the emitted event.
        ``PROVIDER_RESOLVED_FAILED`` is appended to ``events_log`` (sync) before
        any resolution failure is raised.
        """
        if "__default__" in self._resolved:
            return self._resolved["__default__"]
        model, pname, mname, source = resolve_model(
            None,
            providers,
            default_provider,
            self,
            env,
            events_log=events_log,
        )
        if events_log is not None and pname:
            from mage.orchestration.events import Event, EventType

            events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.PROVIDER_RESOLVED,
                    payload={
                        "agent_name": None,
                        "provider": pname,
                        "model_name": mname,
                        "source": source,
                    },
                )
            )
        result = (model, pname, mname)
        self._resolved["__default__"] = result
        return result


async def resolve_model_logged(
    mage_toml: MageTomlConfig,
    agent_name: AgentName | None,
    *,
    providers: dict[str, Any],
    default_provider: str,
    env: dict[str, str],
    events_log: Any | None = None,
) -> tuple[Model, str, str]:
    """Resolve a model, flushing ``PROVIDER_RESOLVED`` + ``PROVIDER_RESOLVED_FAILED``
    into an async events log.

    ``model_for`` / ``default_model_instance`` call ``events_log.append``
    synchronously, but :meth:`mage.orchestration.events.EventsLog.append` is a
    coroutine function. Handing the log straight to them would build a
    coroutine nobody awaits and silently drop the event, so collect into a sync
    sink first and await each collected event here.

    When resolution fails, ``PROVIDER_RESOLVED_FAILED`` is appended to the
    sync sink before the typed exception is raised; we still flush collected
    events (the failure record included) so the audit trail survives the
    re-raise.

    ``agent_name=None`` resolves the default tier (reviewer registry).
    """
    collected: list[Any] = []
    if events_log is None:
        sink = None
    else:
        sink = SimpleNamespace(append=collected.append)
    if agent_name is None:
        try:
            result = mage_toml.default_model_instance(
                providers=providers,
                default_provider=default_provider,
                env=env,
                events_log=sink,
            )
        except Exception:
            if events_log is not None:
                for event in collected:
                    await events_log.append(event)
            raise
    else:
        try:
            result = mage_toml.model_for(
                agent_name,
                providers=providers,
                default_provider=default_provider,
                env=env,
                events_log=sink,
            )
        except Exception:
            if events_log is not None:
                for event in collected:
                    await events_log.append(event)
            raise
    if events_log is not None:
        for event in collected:
            await events_log.append(event)
    return result


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
