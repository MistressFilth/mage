"""Static guards pinning P31 surface against regression (P31 task 12)."""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src" / "mage"
PROVIDERS = SRC / "providers"
HOST_PROJ = SRC / "host_project_config.py"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _grep(pattern: str, root: Path) -> list[tuple[Path, int, str]]:
    rx = re.compile(pattern)
    hits = []
    for path in root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if rx.search(line):
                hits.append((path.relative_to(REPO_ROOT), lineno, line.strip()))
    return hits


class TestKnownProvidersPinned:
    def test_literal_set(self):
        from mage.providers.registry import KNOWN_PROVIDERS

        assert KNOWN_PROVIDERS == frozenset({"anthropic", "minimax"})


class TestAgentNamePinned:
    def test_literal_set(self):
        import typing

        from mage.host_project_config import AgentName

        assert set(typing.get_args(AgentName)) == {
            "inscribe",
            "realize",
            "etch",
            "cosmetic_refiner",
        }


class TestProviderConfigExtraForbid:
    def test_class_has_extra_forbid(self):
        text = _read(PROVIDERS / "config.py")
        assert "class ProviderConfig" in text
        # ProviderConfig block has extra="forbid" somewhere.
        m = re.search(r"class ProviderConfig.*?(?=\nclass |\Z)", text, re.DOTALL)
        assert m is not None
        assert 'extra="forbid"' in m.group(0) or "extra='forbid'" in m.group(0)


class TestMageTomlConfigExtraForbid:
    def test_class_has_extra_forbid(self):
        text = _read(HOST_PROJ)
        m = re.search(r"class MageTomlConfig.*?(?=\nclass |\Z)", text, re.DOTALL)
        assert m is not None
        assert 'extra="forbid"' in m.group(0) or "extra='forbid'" in m.group(0)


class TestNoLegacyEnvVar:
    def test_no_mage_host_model_api_key_literal_in_src(self):
        hits = _grep(r"MAGE_HOST_MODEL_API_KEY", SRC)
        assert hits == [], f"MAGE_HOST_MODEL_API_KEY still referenced: {hits}"


class TestNoHostConfigDotModel:
    def test_no_attribute_access_in_src(self):
        hits = _grep(r"host_config\.model\b", SRC)
        assert hits == [], f"host_config.model still referenced: {hits}"


class TestNoBareEnvReadsInProviders:
    def test_no_os_environ_subscript_in_providers(self):
        hits = _grep(r"os\.environ\[", PROVIDERS)
        assert hits == [], (
            f"bare os.environ[...] read in providers; channel through provider.api_key_env: {hits}"
        )
