"""Provider name → Model factory (P31).

Both built-in providers (anthropic, minimax) route through pydantic-ai's
AnthropicModel — MiniMax uses the same SDK with a different base_url.
``register_provider`` is the extension hook for future providers.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from pydantic_ai.models import Model
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.providers.anthropic import AnthropicProvider

from mage.providers.config import ProviderConfig
from mage.providers.errors import MageUnknownProviderError

__all__ = ["KNOWN_PROVIDERS", "build_model", "register_provider"]

# Pinned by tests/unit/test_static_guards_p31.py.
KNOWN_PROVIDERS: frozenset[str] = frozenset({"anthropic", "minimax"})


def _anthropic_factory(provider: ProviderConfig, model_name: str) -> AnthropicModel:
    return AnthropicModel(
        model_name,
        provider=AnthropicProvider(api_key=os.getenv(provider.api_key_env)),
    )


def _minimax_factory(provider: ProviderConfig, model_name: str) -> AnthropicModel:
    assert provider.base_url is not None
    return AnthropicModel(
        model_name,
        provider=AnthropicProvider(
            api_key=os.getenv(provider.api_key_env),
            base_url=provider.base_url,
        ),
    )


_FACTORIES: dict[str, Callable[[ProviderConfig, str], Model]] = {
    "anthropic": _anthropic_factory,
    "minimax": _minimax_factory,
}


def register_provider(
    name: str, factory: Callable[[ProviderConfig, str], Model]
) -> None:
    """Register a new provider factory at runtime."""
    _FACTORIES[name] = factory


def build_model(name: str, provider: ProviderConfig, model_name: str) -> Model:
    """Construct a pydantic-ai Model for ``name`` + ``provider`` + ``model_name``.

    ``name`` is the dict key in ``[providers.<name>]``. ``provider`` is
    the matching ``ProviderConfig``. ``model_name`` is the model ID string.
    """
    factory = _FACTORIES.get(name)
    if factory is None:
        raise MageUnknownProviderError(name)
    return factory(provider, model_name)
