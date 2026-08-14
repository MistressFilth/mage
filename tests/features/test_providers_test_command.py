"""End-to-end test for ``mage providers test``.

The command is exercised through the installed console script in a real
subprocess, so nothing in the parent process can be monkeypatched into the
run. The provider's Anthropic-compatible endpoint is therefore faked at the
only seam a subprocess honours: the network. A loopback HTTP server stands in
for ``https://api.<provider>/anthropic`` and the XDG config written for the
run points ``base_url`` at it, which keeps the real ``anthropic`` SDK, the
real probe, and the real CLI wiring in the code path under test.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator, Mapping
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
# The console script from *this* checkout's venv, not whatever ``mage`` a
# developer happens to have on PATH from a global ``uv tool install``.
# Windows puts console scripts in ``Scripts/`` with an ``.exe`` suffix.
MAGE_BIN = (
    REPO / ".venv" / "Scripts" / "mage.exe"
    if sys.platform == "win32"
    else REPO / ".venv" / "bin" / "mage"
)

_MODELS_OK = {
    "data": [
        {
            "id": "MiniMax-M3",
            "type": "model",
            "display_name": "MiniMax M3",
            "created_at": "2025-01-01T00:00:00Z",
        }
    ],
    "has_more": False,
    "first_id": "MiniMax-M3",
    "last_id": "MiniMax-M3",
}

_UNAUTHORIZED = {
    "type": "error",
    "error": {"type": "authentication_error", "message": "simulated 401"},
}


def _handler_for(
    status: int, payload: Mapping[str, object]
) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # BaseHTTPRequestHandler's required spelling
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            """Silence the default stderr access log."""

    return _Handler


def _serve(status: int, payload: Mapping[str, object]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(status, payload))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.fixture
def fake_provider_ok() -> Iterator[str]:
    """Base URL of a loopback endpoint that lists ``MiniMax-M3``."""
    yield from _serve(200, _MODELS_OK)


@pytest.fixture
def fake_provider_401() -> Iterator[str]:
    """Base URL of a loopback endpoint that rejects the credential."""
    yield from _serve(401, _UNAUTHORIZED)


def _xdg_config(root: Path, base_url: str) -> Path:
    """Write ``<root>/mage/config.toml`` for one provider; return ``root``."""
    cfg_dir = root / "mage"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.toml").write_text(
        'default_provider = "minimax"\n\n'
        "[providers.minimax]\n"
        f'base_url = "{base_url}"\n'
        'default_model = "MiniMax-M3"\n'
        'api_key_env = "MAGE_TEST_KEY"\n',
        encoding="utf-8",
    )
    return root


def _mage(*args: str, config_root: Path) -> subprocess.CompletedProcess[str]:
    assert MAGE_BIN.exists(), f"{MAGE_BIN} missing; run `make init`"
    env = os.environ.copy()
    env["MAGE_XDG_CONFIG_HOME"] = str(config_root)
    env["MAGE_TEST_KEY"] = "sk-test"
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"
    # The human format prints ✓ / ⚠ / ✗; a non-UTF-8 console codec (Windows'
    # default) would make the child die on encode rather than fail an assert.
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [str(MAGE_BIN), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        env=env,
        cwd=str(REPO),
        timeout=60,
    )


def test_providers_test_json_exits_zero_when_probe_succeeds(
    tmp_path: Path, fake_provider_ok: str
) -> None:
    root = _xdg_config(tmp_path / "config", fake_provider_ok)

    proc = _mage("providers", "test", "--format", "json", config_root=root)

    assert proc.returncode == 0, proc.stderr
    parsed = json.loads(proc.stdout)
    assert parsed["ok"] is True
    assert parsed["providers"][0]["name"] == "minimax"
    assert parsed["providers"][0]["network_ok"] is True
    assert parsed["providers"][0]["default_model_present"] is True


def test_providers_test_json_exits_one_on_network_failure(
    tmp_path: Path, fake_provider_401: str
) -> None:
    root = _xdg_config(tmp_path / "config", fake_provider_401)

    proc = _mage("providers", "test", "--format", "json", config_root=root)

    assert proc.returncode == 1, proc.stderr
    parsed = json.loads(proc.stdout)
    assert parsed["ok"] is False
    assert parsed["providers"][0]["network_ok"] is False
    assert "simulated 401" in parsed["providers"][0]["error"]


def test_providers_test_human_prints_glyph(
    tmp_path: Path, fake_provider_ok: str
) -> None:
    root = _xdg_config(tmp_path / "config", fake_provider_ok)

    proc = _mage("providers", "test", config_root=root)

    assert proc.returncode == 0, proc.stderr
    assert "✓" in proc.stdout
    assert "1 ok, 0 failed" in proc.stdout
