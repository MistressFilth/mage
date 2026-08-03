"""`mage cosmetic unwatch` scenario tests."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from mage import cli
from mage.cosmetic_pid import pid_file_path, write_pid


def _make_mage_dir(project_dir: Path) -> None:
    (project_dir / ".mage").mkdir(parents=True, exist_ok=True)


class _Args:
    def __init__(self, *, project_dir: Path, force: bool = False) -> None:
        self.project_dir = project_dir
        self.force = force


def test_unwatch_no_watcher_returns_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_mage_dir(tmp_path)
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path)))
    assert rc == 0
    out = capsys.readouterr()
    assert "no watcher running" in out.err


def test_unwatch_stale_pid_returns_0_and_removes(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_mage_dir(tmp_path)
    write_pid(tmp_path, 2_000_000_000)  # dead pid
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path)))
    assert rc == 0
    assert not pid_file_path(tmp_path).exists()
    out = capsys.readouterr()
    assert "stale" in out.err


def test_unwatch_self_clean_stop_returns_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_mage_dir(tmp_path)
    write_pid(tmp_path, os.getpid())
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path)))
    assert rc == 0
    assert not pid_file_path(tmp_path).exists()


def test_unwatch_force_succeeds_on_alive_pid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _make_mage_dir(tmp_path)
    write_pid(tmp_path, os.getpid())
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path, force=True)))
    assert rc == 0
    assert not pid_file_path(tmp_path).exists()


def test_unwatch_timeout_returns_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Force the inner wait-loop to time out by patching is_alive to always True."""
    from mage import cli as cli_module

    _make_mage_dir(tmp_path)
    write_pid(tmp_path, os.getpid())
    monkeypatch.setattr(cli_module, "is_alive", lambda _pid: True)
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path)))
    assert rc == 3


def test_unwatch_project_dir_default_is_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When --project-dir is not set, unwatch reads from cwd."""
    _make_mage_dir(tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _Args(project_dir=tmp_path)  # direct attribute
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(args))
    assert rc == 0
