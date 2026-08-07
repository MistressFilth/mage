"""Cross-platform user-directory resolution."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from mage import xdg


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every MAGE_XDG_* and XDG_* var so tests start from a clean slate."""
    for var in (
        "MAGE_XDG_DATA_HOME",
        "MAGE_XDG_CONFIG_HOME",
        "MAGE_XDG_CACHE_HOME",
        "MAGE_XDG_STATE_HOME",
        "MAGE_XDG_RUNTIME_DIR",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
        "XDG_STATE_HOME",
        "XDG_RUNTIME_DIR",
    ):
        monkeypatch.delenv(var, raising=False)


class TestEnvPath:
    def test_returns_none_when_unset(self) -> None:
        assert xdg.env_path("MAGE_XDG_DATA_HOME") is None

    def test_returns_none_when_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGE_XDG_DATA_HOME", "")
        assert xdg.env_path("MAGE_XDG_DATA_HOME") is None

    def test_returns_none_when_relative(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGE_XDG_DATA_HOME", "relative/path")
        assert xdg.env_path("MAGE_XDG_DATA_HOME") is None

    def test_expands_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGE_XDG_DATA_HOME", "~/custom")
        assert xdg.env_path("MAGE_XDG_DATA_HOME") == Path("~/custom").expanduser()

    def test_returns_absolute_path(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MAGE_XDG_DATA_HOME", "/abs/path")
        assert xdg.env_path("MAGE_XDG_DATA_HOME") == Path("/abs/path")


class TestPrecedence:
    def test_mage_xdg_wins_over_xdg(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MAGE_XDG_DATA_HOME", "/mage")
        monkeypatch.setenv("XDG_DATA_HOME", "/xdg")
        assert xdg.data_home() == Path("/mage")

    def test_xdg_wins_over_platform_default(
        self, monkeypatch: pytest.MonkeyPatch, mocker: pytest.Mocker
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", "/xdg")
        mocker.patch(
            "platformdirs.user_data_dir", return_value="/native"
        )
        assert xdg.data_home() == Path("/xdg")

    def test_falls_back_to_platform_default(
        self, mocker: pytest.Mocker
    ) -> None:
        mocker.patch(
            "platformdirs.user_data_dir", return_value="/native"
        )
        assert xdg.data_home() == Path("/native")


class TestSanitizedEnv:
    def test_invalid_relative_xdg_value_is_ignored(
        self, monkeypatch: pytest.MonkeyPatch, mocker: pytest.Mocker
    ) -> None:
        """A relative XDG_DATA_HOME must not leak through platformdirs."""
        monkeypatch.setenv("XDG_DATA_HOME", "relative")
        captured: dict[str, str | None] = {}

        def fake_user_data_dir() -> str:
            captured["XDG_DATA_HOME"] = os.environ.get("XDG_DATA_HOME")
            return "/native"

        mocker.patch("platformdirs.user_data_dir", side_effect=fake_user_data_dir)
        result = xdg.data_home()
        assert result == Path("/native")
        assert captured["XDG_DATA_HOME"] is None

    def test_valid_absolute_xdg_value_passes_through(
        self, monkeypatch: pytest.MonkeyPatch, mocker: pytest.Mocker
    ) -> None:
        monkeypatch.setenv("XDG_DATA_HOME", "/xdg")
        mocker.patch("platformdirs.user_data_dir", return_value="/native")
        assert xdg.data_home() == Path("/xdg")
