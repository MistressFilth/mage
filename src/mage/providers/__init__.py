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

__all__ = [
    "MageInvalidModelStringError",
    "MageMissingApiKeyError",
    "MageProviderError",
    "MageUnknownProviderError",
    "ProviderConfig",
    "load_xdg_providers",
]
