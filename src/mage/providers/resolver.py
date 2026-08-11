"""resolve_model: walk the 5-tier precedence chain (P31)."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any

from pydantic_ai.models import Model
from pydantic_ai.models.test import TestModel

from mage.providers.config import ProviderConfig
from mage.providers.errors import (
    MageInvalidModelStringError,
    MageMissingApiKeyError,
    MageUnknownProviderError,
)
from mage.providers.registry import build_model

__all__ = ["is_test_mode", "resolve_model"]


def is_test_mode(model: Any) -> bool:
    """True when ``model`` selects an agent's deterministic no-LLM passthrough.

    Covers the three ways test mode is expressed: no model at all, the legacy
    ``"test"`` sentinel, and the :class:`TestModel` instance that tier 5 of
    :func:`resolve_model` returns when nothing is configured.
    """
    return model is None or model == "test" or isinstance(model, TestModel)


def _parse_model_string(value: str) -> tuple[str | None, str]:
    """Split 'provider:model' or 'model'. Raises on >1 colons."""
    parts = value.split(":")
    if len(parts) > 2:
        raise MageInvalidModelStringError(value)
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, parts[0]


def _record_failure(events_log: Any, **payload: Any) -> None:
    """Append a PROVIDER_RESOLVED_FAILED event when ``events_log`` is supplied.

    ``events_log`` is typed as ``Any`` so both the sync-test sentinel shape
    (a SimpleNamespace with sync ``append``) and the real async
    :class:`EventsLog` flow through. ``EventsLog.append`` is a coroutine —
    callers that pass the real log MUST drive this through an async
    coroutine themselves (see :func:`mage.host_project_config.resolve_model_logged`).
    """
    if events_log is None:
        return
    from mage.orchestration.events import Event, EventType

    events_log.append(
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.PROVIDER_RESOLVED_FAILED,
            payload=payload,
        )
    )


def _resolve(
    raw: str,
    providers: dict[str, ProviderConfig],
    default_provider: str,
    *,
    events_log: Any = None,
    source: str | None = None,
) -> tuple[Model, str, str]:
    """Resolve a model string to (model, provider_name, model_name)."""
    pname, mname = _parse_model_string(raw)
    chosen = pname if pname is not None else default_provider
    provider = providers.get(chosen)
    if provider is None:
        _record_failure(
            events_log,
            reason="unknown_provider",
            source=source,
            provider=chosen,
            model_name=mname,
        )
        raise MageUnknownProviderError(chosen)
    api_key = os.getenv(provider.api_key_env)
    if api_key is None:
        _record_failure(
            events_log,
            reason="missing_api_key",
            source=source,
            provider=chosen,
            model_name=mname,
            env_var=provider.api_key_env,
        )
        raise MageMissingApiKeyError(env_var=provider.api_key_env, provider=chosen)
    try:
        model = build_model(chosen, provider, mname)
    except Exception as exc:
        _record_failure(
            events_log,
            reason="build_model_failed",
            source=source,
            provider=chosen,
            model_name=mname,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise
    return model, chosen, mname


def resolve_model(
    agent_name: str | None,
    providers: dict[str, ProviderConfig],
    default_provider: str,
    host_cfg: Any,
    env: dict[str, str],
    *,
    events_log: Any = None,
) -> tuple[Model, str, str, str]:
    """Resolve a model for ``agent_name`` through 5 precedence tiers.

    Returns ``(model, provider_name, model_name, source)`` where ``source``
    is one of ``{"env", "mage_toml_agent", "mage_toml_default",
    "xdg_default", "test_model"}``.

    ``env`` is accepted for API symmetry with future injection paths; the
    current implementation reads ``MAGE_MODEL_<AGENT>`` from the process
    environment (``os.getenv``) so ``pytest.MonkeyPatch.setenv`` flows
    through naturally.

    When ``events_log`` is supplied, a ``PROVIDER_RESOLVED_FAILED`` event is
    appended (sync sink) before raising for any resolution failure. Callers
    that pass the real async :class:`EventsLog` must drive the appended
    coroutines through an async wrapper; :func:`mage.host_project_config.resolve_model_logged`
    does this for the mage_toml resolver path.
    """
    # Tier 1: env override per agent.
    if agent_name is not None:
        env_key = f"MAGE_MODEL_{agent_name.upper()}"
        raw = os.getenv(env_key)
        if raw is not None:
            model, pname, mname = _resolve(
                raw, providers, default_provider, events_log=events_log, source="env"
            )
            return model, pname, mname, "env"

    # Tier 2: mage.toml per-agent.
    if agent_name is not None and host_cfg is not None:
        agent_models = getattr(host_cfg, "agent_models", None) or {}
        raw = agent_models.get(agent_name)
        if raw is not None:
            model, pname, mname = _resolve(
                raw,
                providers,
                default_provider,
                events_log=events_log,
                source="mage_toml_agent",
            )
            return model, pname, mname, "mage_toml_agent"

    # Tier 3: mage.toml default_model.
    if host_cfg is not None:
        raw = getattr(host_cfg, "default_model", None)
        if raw is not None:
            model, pname, mname = _resolve(
                raw,
                providers,
                default_provider,
                events_log=events_log,
                source="mage_toml_default",
            )
            return model, pname, mname, "mage_toml_default"

    # Tier 4: XDG default provider's default_model.
    provider = providers.get(default_provider)
    if provider is not None:
        raw = f"{default_provider}:{provider.default_model}"
        model, pname, mname = _resolve(
            raw,
            providers,
            default_provider,
            events_log=events_log,
            source="xdg_default",
        )
        return model, pname, mname, "xdg_default"

    # Tier 5: TestModel fallback (test mode).
    return TestModel(), "", "", "test_model"
