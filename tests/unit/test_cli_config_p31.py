"""cli_config init/show output includes providers + mage.toml sections (P31 task 11)."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from mage.cli_config import cmd_config_init, cmd_config_show


class TestConfigInitWritesProviders:
    def test_init_writes_providers_block(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Redirect XDG_CONFIG_HOME to tmp_path.
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        rc = cmd_config_init()
        assert rc == 0
        cfg = (tmp_path / "mage" / "config.toml").read_text()
        assert "[providers.anthropic]" in cfg
        assert "[providers.minimax]" in cfg
        assert "ANTHROPIC_API_KEY" in cfg
        assert "MINIMAX_API_KEY" in cfg


class TestConfigShowIncludesProviders:
    def test_show_includes_providers_section(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
        # First init.
        assert cmd_config_init() == 0
        rc = cmd_config_show()
        assert rc == 0
        captured = capsys.readouterr()
        assert "[providers]" in captured.out
        assert "anthropic" in captured.out
        assert "minimax" in captured.out

    def test_show_includes_mage_toml_section(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (tmp_path / "mage.toml").write_text(
            textwrap.dedent(
                """\
                default_model = "claude-sonnet-5-20251001"

                [agents]
                inscribe = "minimax:MiniMax-M3"
                """
            )
        )
        rc = cmd_config_show(project_root=tmp_path)
        assert rc == 0
        captured = capsys.readouterr()
        assert "[mage.toml]" in captured.out
        assert "minimax:MiniMax-M3" in captured.out
