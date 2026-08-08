"""Error types for the provider registry (P31)."""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "MageInvalidModelStringError",
    "MageMissingApiKeyError",
    "MageProviderError",
    "MageUnknownProviderError",
]


class MageProviderError(RuntimeError):
    """Base class for provider resolution failures.

    Carries ``source_path`` so CLI error formatter can blame the
    offending file (mage.toml or XDG config.toml). ``None`` when the
    failure origin is not a file (e.g. an unset env var).
    """

    def __init__(self, message: str, *, source_path: Path | None = None) -> None:
        self.source_path = source_path
        super().__init__(message)


class MageUnknownProviderError(MageProviderError):
    """A referenced provider name is not in the registry."""

    def __init__(self, name: str, *, source_path: Path | None = None) -> None:
        self.name = name
        super().__init__(f"unknown provider {name!r}", source_path=source_path)


class MageMissingApiKeyError(MageProviderError):
    """A provider's ``api_key_env`` is unset when ``model_for`` was called."""

    def __init__(
        self, *, env_var: str, provider: str, source_path: Path | None = None
    ) -> None:
        self.env_var = env_var
        self.provider = provider
        super().__init__(
            f"provider {provider!r} requires env var {env_var!r} to be set",
            source_path=source_path,
        )


class MageInvalidModelStringError(MageProviderError):
    """A model string in mage.toml is malformed (more than one colon)."""

    def __init__(self, value: str, *, source_path: Path | None = None) -> None:
        self.value = value
        super().__init__(
            f"invalid model string {value!r} (expected 'model' or 'provider:model')",
            source_path=source_path,
        )
