"""Provider connectivity probe.

Pure-function probe that validates configuration and exercises a single
HTTP request against the provider's models endpoint. Returns a
:class:`ProbeResult` describing what was checked and what failed.
"""

from __future__ import annotations

import os
import time
from typing import Any
from urllib.parse import urlparse

from anthropic import Anthropic
from pydantic import BaseModel

from mage.providers.config import ProviderConfig

__all__ = ["ProbeResult", "probe_provider"]

_NETWORK_TIMEOUT_SECONDS = 10.0


class ProbeResult(BaseModel):
    """Outcome of probing a single provider."""

    name: str
    base_url: str | None
    default_model: str | None
    config_ok: bool
    network_ok: bool
    default_model_present: bool | None
    models: list[str]
    latency_ms: int | None
    error: str | None


def _config_error(name: str, cfg: ProviderConfig, msg: str) -> ProbeResult:
    return ProbeResult(
        name=name,
        base_url=cfg.base_url,
        default_model=cfg.default_model,
        config_ok=False,
        network_ok=False,
        default_model_present=None,
        models=[],
        latency_ms=None,
        error=msg,
    )


def _check_config(cfg: ProviderConfig) -> str | None:
    """Return None if config is OK, else an error message."""
    if not cfg.api_key_env:
        return "missing api_key_env"
    key = os.getenv(cfg.api_key_env)
    if not key:
        return f"${cfg.api_key_env} is empty"
    if key.startswith("<unset>"):
        return f"${cfg.api_key_env} has placeholder value"
    if cfg.base_url is not None:
        try:
            parsed = urlparse(cfg.base_url)
            if not parsed.scheme or not parsed.netloc:
                return f"invalid base_url: {cfg.base_url!r}"
        except ValueError as exc:
            return f"invalid base_url: {exc}"
    return None


def probe_provider(name: str, cfg: ProviderConfig) -> ProbeResult:
    """Probe a single provider. Network call only runs if config is valid."""
    config_error = _check_config(cfg)
    if config_error is not None:
        return _config_error(name, cfg, config_error)

    kwargs: dict[str, Any] = {"api_key": os.getenv(cfg.api_key_env)}
    if cfg.base_url is not None:
        kwargs["base_url"] = cfg.base_url

    try:
        client = Anthropic(**kwargs)
        start = time.monotonic()
        page = client.models.list(timeout=_NETWORK_TIMEOUT_SECONDS)
        latency_ms = int((time.monotonic() - start) * 1000)
    except Exception as exc:  # noqa: BLE001  surface SDK error class verbatim
        return ProbeResult(
            name=name,
            base_url=cfg.base_url,
            default_model=cfg.default_model,
            config_ok=True,
            network_ok=False,
            default_model_present=None,
            models=[],
            latency_ms=None,
            error=f"{type(exc).__name__}: {exc}",
        )

    models = [m.id for m in page.data]

    if cfg.default_model is None:
        present: bool | None = None
    else:
        present = cfg.default_model in models

    return ProbeResult(
        name=name,
        base_url=cfg.base_url,
        default_model=cfg.default_model,
        config_ok=True,
        network_ok=True,
        default_model_present=present,
        models=models,
        latency_ms=latency_ms,
        error=None,
    )
