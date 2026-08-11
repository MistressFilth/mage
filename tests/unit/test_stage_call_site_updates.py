"""Pin that stage call sites no longer read host_config.model (P31 task 10)."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "mage"


def _grep(pattern: str, root: Path) -> list[tuple[Path, int, str]]:
    """Grep for pattern; return [(file, line, content)]."""
    hits = []
    rx = re.compile(pattern)
    paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
    for path in paths:
        if "__pycache__" in str(path):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if rx.search(line):
                hits.append((path.relative_to(REPO_ROOT), lineno, line))
    return hits


class TestNoMoreHostConfigModel:
    def test_no_host_config_dot_model_in_src(self):
        hits = _grep(r"host_config\.model\b", SRC)
        assert hits == [], f"host_config.model still referenced: {hits}"

    def test_no_HostConfig_model_kwarg_in_src(self):
        hits = _grep(r"HostConfig\(\s*model\s*=", SRC)
        assert hits == [], f"HostConfig(model=...) still present: {hits}"

    def test_no_model_kwarg_in_main_cli(self):
        cli = SRC / "cli.py"
        hits = _grep(r"['\"]--model['\"]", cli)
        assert hits == [], f"--model flag still present in cli.py: {hits}"


class TestModelFlagRejected:
    """`--model` is gone from the parsers, so argparse must reject it."""

    def test_run_rejects_model_flag(self):
        import pytest

        from mage.cli import main

        with pytest.raises(SystemExit) as exc:
            main(["run", "--model", "test"])
        assert exc.value.code == 2

    def test_cosmetic_apply_rejects_model_flag(self):
        import pytest

        from mage.cli import main

        with pytest.raises(SystemExit) as exc:
            main(["cosmetic", "apply", "feat-1", "--model", "test"])
        assert exc.value.code == 2
