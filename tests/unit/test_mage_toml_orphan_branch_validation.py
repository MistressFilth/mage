"""Tests for MageTomlConfig.orphan_branch field validation (P32)."""

from __future__ import annotations

import pytest

from mage.host_project_config import MageTomlConfig
from mage.settings import MageConfigurationError


def test_orphan_branch_default_is_feature_artifacts() -> None:
    cfg = MageTomlConfig()
    assert cfg.orphan_branch == "feature-artifacts"


@pytest.mark.parametrize(
    "value",
    [
        "valid-name",
        "valid_name",
        "valid.name",
        "with/slashes",
        "MixedCase",
        "123",
        "a",
    ],
)
def test_orphan_branch_accepts_valid_values(value: str) -> None:
    cfg = MageTomlConfig(orphan_branch=value)
    assert cfg.orphan_branch == value


@pytest.mark.parametrize(
    "value",
    [
        ".hidden",  # leading dot
        "trailing.lock",  # trailing .lock
        "",  # empty
        "../escape",  # path traversal
        "has space",  # space
        "has:colon",  # colon (git ref forbidden)
        "has~tilde",  # tilde (git ref forbidden)
        "a" * 201,  # too long
    ],
)
def test_orphan_branch_rejects_invalid_values(value: str) -> None:
    with pytest.raises((ValueError, MageConfigurationError)):
        MageTomlConfig(orphan_branch=value)
