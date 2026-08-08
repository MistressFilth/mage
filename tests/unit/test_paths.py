"""Application directory layout."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pytest_mock import MockerFixture

from mage import paths, xdg


@pytest.fixture(autouse=True)
def isolated_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point every XDG root at a tmp dir so tests don't touch the real filesystem."""
    for var in (
        "MAGE_XDG_DATA_HOME",
        "MAGE_XDG_CONFIG_HOME",
        "MAGE_XDG_CACHE_HOME",
        "MAGE_XDG_STATE_HOME",
        "MAGE_XDG_RUNTIME_DIR",
    ):
        monkeypatch.setenv(var, str(tmp_path))


class TestComposition:
    def test_app_data_dir(self) -> None:
        assert paths.app_data_dir() == xdg.data_home() / "mage"

    def test_app_config_dir(self) -> None:
        assert paths.app_config_dir() == xdg.config_home() / "mage"

    def test_app_cache_dir(self) -> None:
        assert paths.app_cache_dir() == xdg.cache_home() / "mage"

    def test_app_state_dir(self) -> None:
        assert paths.app_state_dir() == xdg.state_home() / "mage"

    def test_app_data_dir_does_not_create(self, tmp_path: Path) -> None:
        paths.app_data_dir()
        assert not (tmp_path / "mage").exists()


class TestAppRuntimeDir:
    def test_creates_directory(self, tmp_path: Path) -> None:
        result = paths.app_runtime_dir()
        assert result.exists()
        assert result.is_dir()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason=(
            "WindowsPath has no POSIX mode bits; chmod(0o700) on a "
            "WindowsPath sets FILE_ATTRIBUTE_READONLY instead and the "
            "stat-st_mode 0o700 assertion cannot hold."
        ),
    )
    def test_applies_chmod_on_posix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "name", "posix")
        result = paths.app_runtime_dir()
        mode = result.stat().st_mode & 0o777
        assert mode == 0o700

    @pytest.mark.skipif(
        os.name == "posix",
        reason="Cannot simulate os.name=='nt' on POSIX: Path() becomes WindowsPath",
    )
    def test_skips_chmod_on_windows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "name", "nt")
        # Should not raise even though chmod is a no-op on Windows.
        result = paths.app_runtime_dir()
        assert result.exists()

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason=(
            "chmod(0o500) on Windows sets FILE_ATTRIBUTE_READONLY and does "
            "not block directory writes; the production code's mkdir "
            "fallback path cannot be triggered without OS-specific ACL "
            "manipulation."
        ),
    )
    def test_falls_back_on_mkdir_failure(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        mocker: MockerFixture,
    ) -> None:
        """If XDG_RUNTIME_DIR is unwritable, fall back to state/run."""
        unwritable = tmp_path / "unwritable"
        unwritable.mkdir()
        monkeypatch.setenv("MAGE_XDG_RUNTIME_DIR", str(unwritable))

        # Make the unwritable dir actually unwritable by removing write bits.
        unwritable.chmod(0o500)

        try:
            result = paths.app_runtime_dir()
        finally:
            unwritable.chmod(0o700)

        # Fallback lives under state_home/mage/run.
        expected = xdg.state_home() / "mage" / "run"
        assert result == expected
        assert result.exists()
