"""Provider registry + per-agent model resolution (P31).

Public surface re-exported from submodules.
"""

from __future__ import annotations

from mage.providers.config import ProviderConfig, load_xdg_providers
from mage.providers.errors import (
    MageInvalidModelStringError,
    MageMissingApiKeyError,
    MageProviderError,
    MageUnknownProviderError,
)
from mage.providers.registry import (
    KNOWN_PROVIDERS,
    build_model,
    register_provider,
)

__all__ = [
    "KNOWN_PROVIDERS",
    "MageInvalidModelStringError",
    "MageMissingApiKeyError",
    "MageProviderError",
    "MageUnknownProviderError",
    "ProviderConfig",
    "build_model",
    "load_xdg_providers",
    "register_provider",
]
