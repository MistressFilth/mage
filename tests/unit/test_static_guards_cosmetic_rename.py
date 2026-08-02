"""Static guard: enforce the CosmeticItem / CosmeticFinding / CosmeticPatch naming
after the Plan 18 rename. Catches regression if anyone reintroduces a bare
CosmeticItem in src/.

Mirrors the Plan 13 / Plan 15 / Plan 17 static-guard pattern.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"


def _grep(pattern: str, *paths: Path) -> list[str]:
    """Return list of 'path:line' hits for `pattern` in the given paths."""
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py", pattern, *paths],
        capture_output=True,
        text=True,
        check=False,
    )
    return [
        line
        for line in result.stdout.splitlines()
        if line and "test_static_guards_cosmetic_rename.py" not in line
    ]


class TestNoBareCosmeticItem:
    def test_no_class_cosmetic_item_in_src(self):
        hits = _grep(r"class CosmeticItem\b", SRC)
        assert hits == [], (
            "bare 'class CosmeticItem' found in src/; "
            "use CosmeticFinding or CosmeticPatch instead:\n" + "\n".join(hits)
        )

    def test_no_bare_cosmetic_item_token_in_src(self):
        hits = _grep(r"\bCosmeticItem\b", SRC)
        assert hits == [], (
            "bare 'CosmeticItem' reference found in src/; "
            "use CosmeticFinding or CosmeticPatch instead:\n" + "\n".join(hits)
        )


class TestOnDiskAliasPreserved:
    def test_feature_cosmetic_queue_still_referenced(self):
        """The on-disk mapping key must remain stable; the alias keeps it."""
        hits = _grep(r"feature_cosmetic_queue", SRC)
        assert len(hits) > 0, (
            "feature_cosmetic_queue (the on-disk alias) is no longer referenced "
            "in src/; verify the MappingArtifact alias is configured correctly"
        )

    def test_alias_appears_in_mapping_artifact_definition(self):
        """The Pydantic Field alias is the source of truth for the on-disk key.

        A docstring or event-payload reference alone is not sufficient — only
        the literal ``alias=\"feature_cosmetic_queue\"`` on the
        ``cosmetic_findings`` Field actually pins the YAML/JSON key. If this
        assertion fails, the alias was removed from MappingArtifact and the
        on-disk mapping.yaml will start round-tripping under the wrong key.
        """
        import re

        mapping_path = REPO_ROOT / "src/mage/artifacts/mapping.py"
        text = mapping_path.read_text()
        assert 'alias="feature_cosmetic_queue"' in text, (
            f'MappingArtifact no longer pins alias="feature_cosmetic_queue" '
            f"in {mapping_path}; on-disk mapping.yaml will lose its alias key. "
            f"Check that the cosmetic_findings Field still uses "
            f"Field(alias='feature_cosmetic_queue')."
        )
        # And it must be on the cosmetic_findings Field specifically, not on
        # an unrelated attribute — verify by anchoring on the attribute name.
        match = re.search(
            r"cosmetic_findings\s*:[^=\n]*=.*?Field\([^)]*alias=\"feature_cosmetic_queue\"",
            text,
            re.DOTALL,
        )
        assert match is not None, (
            f"alias='feature_cosmetic_queue' is present in {mapping_path} but "
            f"not attached to the cosmetic_findings Field; the on-disk key "
            f"will not be stable."
        )
