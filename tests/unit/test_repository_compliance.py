from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]


def test_agents_contains_complete_pre_pr_checklist() -> None:
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert re.search(r"4\. \*\*Update `docs/`\.\*\*", text)


def test_readme_contains_badge_and_required_links() -> None:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    assert (
        "[![Checks](https://github.com/MistressFilth/mage/actions/workflows/check.yml/badge.svg)]"
        "(https://github.com/MistressFilth/mage/actions/workflows/check.yml)" in text
    )
    assert "- [CHANGELOG.md](CHANGELOG.md)" in text
    assert "- [AGENTS.md](AGENTS.md) — repository conventions for LLM agents" in text


def test_changelog_contains_current_version_heading() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE)
    assert version is not None
    tag_date = subprocess.run(
        ["git", "log", "-1", "--format=%cs", f"refs/tags/v{version.group(1)}"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{version.group(1)}] - {tag_date}" in changelog


def test_checked_out_history_has_no_coauthor_trailers() -> None:
    messages = subprocess.run(
        ["git", "log", "--format=%B", "--all"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    assert (
        re.search(r"^\s*Co-Authored-By:", messages, re.IGNORECASE | re.MULTILINE)
        is None
    )


def test_imported_reviewer_is_not_collected_as_test_class() -> None:
    from mage.verification.reviewers.testability import TestabilityReviewer

    assert getattr(TestabilityReviewer, "__test__", True) is False
