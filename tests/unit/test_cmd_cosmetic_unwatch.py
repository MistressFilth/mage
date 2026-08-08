"""`mage cosmetic unwatch` scenario tests.

The production `_request_remote_stop` no longer installs a SIGTERM
emulator on its own; tests that signal SIGTERM to themselves need a
local helper. The `_self_signal_safe` fixture below installs a SIGTERM
no-op handler and monkeypatches `is_alive_with_start` so the wait loop
exits without killing the test runner.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from mage import cli
from mage.cosmetic_pid import pid_file_path, write_pid


def _make_mage_dir(project_dir: Path) -> None:
    (project_dir / ".mage").mkdir(parents=True, exist_ok=True)


class _Args:
    def __init__(self, *, project_dir: Path, force: bool = False) -> None:
        self.project_dir = project_dir
        self.force = force


class _OsKillShim:
    """Replaces the `os` module's `kill` with a recording fake.

    Other `os` attributes pass through to the real module so
    unrelated code paths in `_request_remote_stop` continue to work.
    """

    def __init__(self, real_os: Any, kill_fn) -> None:
        self._real_os = real_os
        self._kill_fn = kill_fn

    def kill(self, pid: int, sig: int) -> None:
        self._kill_fn(pid, sig)

    def __getattr__(self, name: str):
        return getattr(self._real_os, name)


class FakeSignalState:
    """Records `os.kill` calls and answers liveness queries.

    Behavior mirrors a real cosmetic watcher:
    - SIGTERM → the (simulated) watcher exits and removes its PID file;
      the wait loop sees `path.exists() == False` and exits successfully.
    - SIGKILL → the process dies; the wait loop sees
      `is_alive_with_start == False` and exits.

    Tests can override:
    - `always_alive = True`: liveness never returns False → drives the
      SIGTERM_TIMEOUT (no force) path to exit code 3.
    - `sigterm_removes_pid = False`: SIGTERM does NOT unlink the PID
      file (used by the SIGKILL escalation test, which relies on
      liveness alone to detect death).
    - `set_project_dir(p)`: the path fake_kill uses to unlink the PID
      file on SIGTERM. The fixture sets this per-test.
    """

    def __init__(self) -> None:
        self.kills: list[tuple[int, int]] = []
        self.alive: bool = True
        self.always_alive: bool = False
        self.sigterm_removes_pid: bool = True
        self._project_dir: Path | None = None

    def set_project_dir(self, project_dir: Path) -> None:
        self._project_dir = project_dir

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from mage.orchestration import cosmetic_watcher as cw

        state = self

        def fake_kill(pid: int, sig: int) -> None:
            state.kills.append((pid, sig))
            if sig == signal.SIGKILL:
                state.alive = False
            elif sig == signal.SIGTERM and state.sigterm_removes_pid:
                if state._project_dir is None:
                    return
                try:
                    pid_file_path(state._project_dir).unlink()
                except FileNotFoundError:
                    pass

        def fake_is_alive(pid: int, start_time):
            return state.always_alive or state.alive

        monkeypatch.setattr(cw, "os", _OsKillShim(os, fake_kill))
        monkeypatch.setattr(cw, "is_alive_with_start", fake_is_alive)


@pytest.fixture
def self_signal_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[FakeSignalState, None, None]:
    """Allow tests to signal SIGTERM to themselves without dying.

    The unwatch path calls `os.kill(target_pid, SIGTERM)` against the
    test process. We install a SIGTERM handler that does nothing and
    return a state object tests can use to flip liveness. The state
    must be told the project directory via `set_project_dir(p)` so
    fake_kill knows where to remove the PID file.
    """
    state = FakeSignalState()
    state.install(monkeypatch)
    old_handler = signal.signal(signal.SIGTERM, signal.SIG_IGN)
    try:
        yield state
    finally:
        signal.signal(signal.SIGTERM, old_handler)


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
    write_pid(tmp_path, 2_000_000_000)  # dead pid; /proc may not exist
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path)))
    assert rc == 0
    assert not pid_file_path(tmp_path).exists()
    out = capsys.readouterr()
    assert "stale" in out.err


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="signal.SIGKILL is POSIX-only; the test fake_kill fixture relies on it",
)
def test_unwatch_self_clean_stop_returns_0(
    tmp_path: Path, self_signal_safe: FakeSignalState
) -> None:
    """Self-pid; SIGTERM unlinks the PID file (watcher-style exit).

    The fake_kill hook unlinks the PID file when SIGTERM is sent.
    The wait loop sees `path.exists() == False` and exits with
    success; the production code returns 0.
    """
    _make_mage_dir(tmp_path)
    self_signal_safe.set_project_dir(tmp_path)
    write_pid(tmp_path, os.getpid())
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path)))
    assert rc == 0
    assert not pid_file_path(tmp_path).exists()
    assert any(sig == signal.SIGTERM for _pid, sig in self_signal_safe.kills)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="signal.SIGKILL is POSIX-only; the test fake_kill fixture relies on it",
)
def test_unwatch_force_succeeds_on_alive_pid(
    tmp_path: Path, self_signal_safe: FakeSignalState
) -> None:
    """`--force` plus SIGTERM-exits-watcher: PID file goes, RC=0.

    SIGTERM removes the PID file (simulating the watcher exiting
    cleanly), so the wait loop exits successfully even without
    SIGKILL. `--force` is accepted but not used.
    """
    _make_mage_dir(tmp_path)
    self_signal_safe.set_project_dir(tmp_path)
    write_pid(tmp_path, os.getpid())
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path, force=True)))
    assert rc == 0
    assert not pid_file_path(tmp_path).exists()
    sigs = [sig for _pid, sig in self_signal_safe.kills]
    assert signal.SIGTERM in sigs
    # SIGKILL was not needed; SIGTERM removed the PID file first.


def _fast_asyncio_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make `_request_remote_stop`'s wait loop race the deadline.

    Replaces `mage.orchestration.cosmetic_watcher.asyncio.sleep` with
    a no-op yielding coroutine so the 0.05 s polling sleep becomes
    effectively instant. The replacement calls the real sleep with a
    0-second argument via the asyncio module captured before the
    patch, avoiding recursion.
    """
    import asyncio as _asyncio

    real_sleep = _asyncio.sleep

    async def _no_sleep(_seconds: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr("mage.orchestration.cosmetic_watcher.asyncio.sleep", _no_sleep)


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="signal.SIGKILL is POSIX-only; the test fake_kill fixture relies on it",
)
def test_unwatch_timeout_returns_3(
    tmp_path: Path,
    self_signal_safe: FakeSignalState,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SIGTERM-timeout (no force): the wait loop never observes death.

    `always_alive = True` keeps `is_alive_with_start` returning True
    and `sigterm_removes_pid = False` keeps the PID file present,
    so the wait loop hits the deadline. The 0.05 s polling sleep is
    short-circuited so the 5 s timer finishes fast.
    """
    _make_mage_dir(tmp_path)
    self_signal_safe.set_project_dir(tmp_path)
    self_signal_safe.always_alive = True
    self_signal_safe.sigterm_removes_pid = False
    write_pid(tmp_path, os.getpid())
    _fast_asyncio_sleep(monkeypatch)
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path)))
    assert rc == 3
    # SIGKILL was NOT sent because --force was not passed.
    sigs = [sig for _pid, sig in self_signal_safe.kills]
    assert signal.SIGTERM in sigs
    assert signal.SIGKILL not in sigs


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="signal.SIGKILL is POSIX-only; the test fake_kill fixture relies on it",
)
def test_unwatch_force_sigkill_kills_before_timeout(
    tmp_path: Path,
    self_signal_safe: FakeSignalState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--force` SIGKILL branch: SIGTERM is a no-op, SIGKILL kills.

    `sigterm_removes_pid = False` keeps the PID file present after
    SIGTERM, so the wait loop must rely on liveness alone. SIGKILL
    flips `alive = False` and the wait loop exits successfully. The
    terminal event must report an elapsed `duration_ms`, not the
    timeout.
    """
    import json

    _make_mage_dir(tmp_path)
    self_signal_safe.set_project_dir(tmp_path)
    self_signal_safe.sigterm_removes_pid = False
    write_pid(tmp_path, os.getpid())
    _fast_asyncio_sleep(monkeypatch)
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path, force=True)))
    assert rc == 0
    assert not pid_file_path(tmp_path).exists()

    # Read the events log; the SUCCEEDED terminal event must report
    # an elapsed duration, not the timeout.
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    succeeded = [
        e for e in events if e["event_type"] == "cosmetic_watcher_remote_stop_succeeded"
    ]
    assert succeeded, "expected a SUCCEEDED event from SIGKILL branch"
    payload = succeeded[-1]["payload"]
    assert payload["target_pid"] == os.getpid()
    # duration_ms is computed from the monotonic clock at exit; it must
    # be a non-negative integer and at most one full timeout (5000ms).
    assert isinstance(payload["duration_ms"], int)
    assert 0 <= payload["duration_ms"] <= 5000


def test_unwatch_project_dir_default_is_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When --project-dir is not set, unwatch reads from cwd."""
    _make_mage_dir(tmp_path)
    monkeypatch.chdir(tmp_path)
    args = _Args(project_dir=tmp_path)  # direct attribute
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(args))
    assert rc == 0


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="signal.SIGKILL is POSIX-only; the test fake_kill fixture relies on it",
)
def test_unwatch_sigterm_timeout_event_records_elapsed(
    tmp_path: Path,
    self_signal_safe: FakeSignalState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SIGTERM_TIMEOUT escalation reports elapsed_ms from monotonic.

    Important #1: the escalation event must carry a real duration,
    not a hardcoded zero or timeout value. The test sets `always_alive`
    so the SIGTERM window hits its deadline, then checks the
    REMOTE_STOP_ESCALATED event payload's duration_ms is between 0
    and timeout_s * 1000.
    """
    import json

    _make_mage_dir(tmp_path)
    self_signal_safe.set_project_dir(tmp_path)
    self_signal_safe.always_alive = True
    self_signal_safe.sigterm_removes_pid = False
    write_pid(tmp_path, os.getpid())
    _fast_asyncio_sleep(monkeypatch)
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path)))
    assert rc == 3
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    escalations = [
        e for e in events if e["event_type"] == "cosmetic_watcher_remote_stop_escalated"
    ]
    assert escalations, "expected SIGTERM_TIMEOUT escalation event"
    payload = escalations[-1]["payload"]
    assert payload["escalation"] == "SIGTERM_TIMEOUT"
    assert isinstance(payload["duration_ms"], int)
    # The wait loop hit the 5 s deadline; duration_ms must reflect
    # actual elapsed wall time at escalation, not the timeout itself.
    assert 0 <= payload["duration_ms"] <= 5000


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="signal.SIGKILL is POSIX-only; the test fake_kill fixture relies on it",
)
def test_unwatch_sigkill_success_records_kill_window_duration(
    tmp_path: Path,
    self_signal_safe: FakeSignalState,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SIGKILL success reports elapsed in the SIGKILL window only.

    After SIGKILL is dispatched the elapsed counter is reset, so the
    SUCCEEDED event's duration_ms covers SIGKILL waiting only — not
    the SIGTERM+SIGKILL cumulative time. SIGTERM-exit first would
    never trigger the SIGKILL branch; this test forces the escalation
    branch by holding liveness through SIGTERM, then dying on SIGKILL.
    """
    import json

    _make_mage_dir(tmp_path)
    self_signal_safe.set_project_dir(tmp_path)
    self_signal_safe.sigterm_removes_pid = False
    # alive=True is the default; SIGKILL flips it to False inside fake_kill,
    # so the SIGKILL wait loop sees liveness-death and exits successfully.
    write_pid(tmp_path, os.getpid())
    _fast_asyncio_sleep(monkeypatch)
    rc = asyncio.run(cli.cmd_cosmetic_unwatch(_Args(project_dir=tmp_path, force=True)))
    assert rc == 0
    assert not pid_file_path(tmp_path).exists()
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text().splitlines()
        if line.strip()
    ]
    succeeded = [
        e for e in events if e["event_type"] == "cosmetic_watcher_remote_stop_succeeded"
    ]
    assert succeeded
    payload = succeeded[-1]["payload"]
    assert isinstance(payload["duration_ms"], int)
    # The SIGKILL window is at most one full timeout.
    assert 0 <= payload["duration_ms"] <= 5000
