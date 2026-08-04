"""Unit tests for `mage run --feature-id` plumbing (Plan 22).

Covers the `_resolve_feature_id` helper and the cmd_run integration that
threads the value into PipelineContext / FeatureRunner. Tag-only semantics:
no validation against saved state, no override of Ascertain-derived value.
"""

from __future__ import annotations

import argparse

import pytest

from mage.cli import _resolve_feature_id


class TestResolveFeatureId:
    def test_omitted_returns_empty_string(self):
        """Argparse default=None when flag is not passed → empty string."""

        args = argparse.Namespace(feature_id=None)
        assert _resolve_feature_id(args) == ""

    def test_non_empty_value_returns_stripped(self):
        """Explicit non-empty value passes through unchanged."""

        args = argparse.Namespace(feature_id="feat-X")
        assert _resolve_feature_id(args) == "feat-X"

    def test_empty_string_exits_with_code_2(self):
        """Explicit empty string → SystemExit(2) with stderr message."""

        args = argparse.Namespace(feature_id="")
        with pytest.raises(SystemExit) as exc_info:
            _resolve_feature_id(args)
        assert exc_info.value.code == 2

    def test_whitespace_only_exits_with_code_2(self):
        """Whitespace-only → SystemExit(2)."""

        args = argparse.Namespace(feature_id="   ")
        with pytest.raises(SystemExit) as exc_info:
            _resolve_feature_id(args)
        assert exc_info.value.code == 2

    def test_missing_attribute_returns_empty_string(self):
        """Attribute missing (e.g., from a different parser subcommand) → empty."""

        # no feature_id attribute
        args = argparse.Namespace()
        assert _resolve_feature_id(args) == ""
