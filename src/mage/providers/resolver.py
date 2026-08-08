"""resolve_model: walk the 5-tier precedence chain (P31)."""

from __future__ import annotations

import os
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

__all__ = ["resolve_model"]


def _parse_model_string(value: str) -> tuple[str | None, str]:
    """Split 'provider:model' or 'model'. Raises on >1 colons."""
    parts = value.split(":")
    if len(parts) > 2:
        raise MageInvalidModelStringError(value)
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, parts[0]


def _resolve(
    raw: str,
    providers: dict[str, ProviderConfig],
    default_provider: str,
) -> tuple[Model, str, str]:
    """Resolve a model string to (model, provider_name, model_name)."""
    pname, mname = _parse_model_string(raw)
    chosen = pname if pname is not None else default_provider
    provider = providers.get(chosen)
    if provider is None:
        raise MageUnknownProviderError(chosen)
    api_key = os.getenv(provider.api_key_env)
    if api_key is None:
        raise MageMissingApiKeyError(env_var=provider.api_key_env, provider=chosen)
    model = build_model(chosen, provider, mname)
    return model, chosen, mname


def resolve_model(
    agent_name: str | None,
    providers: dict[str, ProviderConfig],
    default_provider: str,
    host_cfg: Any,
    env: dict[str, str],
) -> tuple[Model, str, str, str]:
    """Resolve a model for ``agent_name`` through 5 precedence tiers.

    Returns ``(model, provider_name, model_name, source)`` where ``source``
    is one of ``{"env", "mage_toml_agent", "mage_toml_default",
    "xdg_default", "test_model"}``.

    ``env`` is accepted for API symmetry with future injection paths; the
    current implementation reads ``MAGE_MODEL_<AGENT>`` from the process
    environment (``os.getenv``) so ``pytest.MonkeyPatch.setenv`` flows
    through naturally.
    """
    # Tier 1: env override per agent.
    if agent_name is not None:
        env_key = f"MAGE_MODEL_{agent_name.upper()}"
        raw = os.getenv(env_key)
        if raw is not None:
            model, pname, mname = _resolve(raw, providers, default_provider)
            return model, pname, mname, "env"

    # Tier 2: mage.toml per-agent.
    if agent_name is not None and host_cfg is not None:
        agent_models = getattr(host_cfg, "agent_models", None) or {}
        raw = agent_models.get(agent_name)
        if raw is not None:
            model, pname, mname = _resolve(raw, providers, default_provider)
            return model, pname, mname, "mage_toml_agent"

    # Tier 3: mage.toml default_model.
    if host_cfg is not None:
        raw = getattr(host_cfg, "default_model", None)
        if raw is not None:
            model, pname, mname = _resolve(raw, providers, default_provider)
            return model, pname, mname, "mage_toml_default"

    # Tier 4: XDG default provider's default_model.
    provider = providers.get(default_provider)
    if provider is not None:
        try:
            model = build_model(default_provider, provider, provider.default_model)
            return model, default_provider, provider.default_model, "xdg_default"
        except Exception:  # noqa: BLE001, S110 — intentional silent fallthrough
            pass

    # Tier 5: TestModel fallback (test mode).
    return TestModel(), "", "", "test_model"
