"""CLI surface for `mage config`."""

from __future__ import annotations

from pathlib import Path

import pytest

from mage import cli_config
from mage.settings import initialize_config


@pytest.fixture(autouse=True)
def isolated_config_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MAGE_XDG_CONFIG_HOME", str(tmp_path))


class TestConfigPath:
    def test_prints_path(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cli_config.cmd_config_path()
        assert rc == 0
        captured = capsys.readouterr()
        assert captured.out.strip().endswith("config.toml")


class TestConfigInit:
    def test_creates_file(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cli_config.cmd_config_init()
        assert rc == 0

    def test_refuses_overwrite(self, capsys: pytest.CaptureFixture[str]) -> None:
        initialize_config()
        rc = cli_config.cmd_config_init()
        assert rc == 2
        captured = capsys.readouterr()
        assert "already exists" in captured.err

    def test_filesystem_failure_exits_2(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        readonly = tmp_path / "readonly"
        readonly.mkdir()
        readonly.chmod(0o500)
        try:
            monkeypatch.setenv("MAGE_XDG_CONFIG_HOME", str(readonly / "subdir"))
            rc = cli_config.cmd_config_init()
            assert rc == 2
            captured = capsys.readouterr()
            assert "could not write" in captured.err
            assert "No traceback" not in captured.err  # implicit: no exception leaks
        finally:
            readonly.chmod(0o700)


class TestConfigShow:
    def test_prints_log_level(self, capsys: pytest.CaptureFixture[str]) -> None:
        initialize_config()
        rc = cli_config.cmd_config_show()
        assert rc == 0
        captured = capsys.readouterr()
        assert 'log_level = "info"' in captured.out

    def test_redacts_secret(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("MAGE_HOST_MODEL_API_KEY", "supersecret")
        rc = cli_config.cmd_config_show()
        assert rc == 0
        captured = capsys.readouterr()
        assert "supersecret" not in captured.out
        assert "***" in captured.out

    def test_invalid_config_exits_2(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        # Hand-craft an invalid TOML file.
        config = tmp_path / "mage" / "config.toml"
        config.parent.mkdir(parents=True)
        config.write_text("malformed [ toml")
        rc = cli_config.cmd_config_show()
        assert rc == 2
