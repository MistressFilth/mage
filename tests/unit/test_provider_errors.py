"""Error class shape pin for mage provider registry (P31)."""

from __future__ import annotations

from pathlib import Path

from mage.providers.errors import (
    MageInvalidModelStringError,
    MageMissingApiKeyError,
    MageProviderError,
    MageUnknownProviderError,
)


class TestMageProviderError:
    def test_base_carries_source_path(self):
        exc = MageProviderError("base", source_path=Path("/x/y.toml"))
        assert exc.source_path == Path("/x/y.toml")
        assert "base" in str(exc)

    def test_base_allows_none_source_path(self):
        exc = MageProviderError("base")
        assert exc.source_path is None


class TestMageUnknownProviderError:
    def test_subclass_and_carries_name(self):
        exc = MageUnknownProviderError("grok", source_path=Path("/x.toml"))
        assert isinstance(exc, MageProviderError)
        assert exc.name == "grok"
        assert exc.source_path == Path("/x.toml")
        assert "grok" in str(exc)


class TestMageMissingApiKeyError:
    def test_carries_env_var_and_provider(self):
        exc = MageMissingApiKeyError(env_var="MINIMAX_API_KEY", provider="minimax")
        assert isinstance(exc, MageProviderError)
        assert exc.env_var == "MINIMAX_API_KEY"
        assert exc.provider == "minimax"
        assert exc.source_path is None
        assert "MINIMAX_API_KEY" in str(exc)


class TestMageInvalidModelStringError:
    def test_carries_value_and_source(self):
        exc = MageInvalidModelStringError("foo:bar:baz", source_path=Path("/x.toml"))
        assert isinstance(exc, MageProviderError)
        assert exc.value == "foo:bar:baz"
        assert "foo:bar:baz" in str(exc)
