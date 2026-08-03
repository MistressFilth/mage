"""Pytest configuration and shared fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_project_dir(tmp_path: Path) -> Path:
    """Provide an isolated project directory for tests."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    return project_dir
