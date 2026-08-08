"""Provider configuration model + XDG loader (P31).

XDG layout: ``~/.config/mage/config.toml`` carries ``[providers.<name>]``
tables plus a top-level ``default_provider`` string.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from mage.paths import app_config_dir
from mage.providers.errors import MageProviderError
from mage.settings import MageConfigurationError

__all__ = ["ProviderConfig", "load_xdg_providers"]


class ProviderConfig(BaseModel):
    """One provider's config block.

    ``name`` is the dict key in ``[providers.<name>]``, not a field.
    """

    model_config = ConfigDict(extra="forbid")

    base_url: str | None = None
    default_model: str
    api_key_env: str
    options: dict[str, Any] = {}


def load_xdg_providers(
    *, path: Path | None = None
) -> tuple[dict[str, ProviderConfig], str]:
    """Load providers from XDG config.toml.

    Returns ``(providers_dict, default_provider_name)``. If the file is
    absent, returns ``({}, "anthropic")`` — the single-provider default.

    Raises :class:`MageProviderError` if ``default_provider`` references a
    missing key, or :class:`MageConfigurationError` for TOML / validation
    failures.
    """
    cfg_path = path if path is not None else app_config_dir() / "config.toml"
    if not cfg_path.exists():
        return ({}, "anthropic")

    try:
        data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise MageConfigurationError(cfg_path, str(exc)) from exc

    providers_raw = data.get("providers", {})
    providers: dict[str, ProviderConfig] = {}
    for name, raw in providers_raw.items():
        try:
            providers[name] = ProviderConfig.model_validate(raw)
        except ValidationError as exc:
            raise MageConfigurationError(cfg_path, str(exc)) from exc

    declared_default = data.get("default_provider")
    if declared_default is None:
        if len(providers) == 1:
            default = next(iter(providers))
        else:
            raise MageProviderError(
                f"multiple providers registered but default_provider not set in {cfg_path}",
                source_path=cfg_path,
            )
    else:
        if declared_default not in providers:
            raise MageProviderError(
                f"default_provider {declared_default!r} not in [providers] table",
                source_path=cfg_path,
            )
        default = declared_default

    return (providers, default)
