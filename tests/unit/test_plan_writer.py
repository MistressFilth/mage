"""Tests for the Plan writer (renders plan.md from behaviors + template)."""

from __future__ import annotations

from pathlib import Path

from mage.artifacts.ascertain import AscertainOutput


TEMPLATE = """---
behavior_ids:
{behavior_ids_yaml}
behaviors:
{behaviors_yaml}
project_id: {project_id}
schema_version: 1
---

# Implementation Plan — {feature_name}

**Goal:** {scope_statement}

## Behaviors

{behavior_sections}
"""


def _two_entries():
    from mage.artifacts.mapping import BaseBIDEntry
    return [
        BaseBIDEntry(base_bid="00000", behavior_name="auth", behavior_description="User logs in", depends_on=[]),
        BaseBIDEntry(base_bid="00001", behavior_name="orders", behavior_description="User places orders", depends_on=["00000"]),
    ]


def test_render_plan_includes_frontmatter(tmp_path):
    from mage.orchestration.plan_writer import render_plan
    template = tmp_path / "tpl.md"
    template.write_text(TEMPLATE, encoding="utf-8")
    ascertain = AscertainOutput(
        feature_id="feat-001",
        feature_name="Auth flow",
        scope_statement="Email/password login.",
    )
    entries = _two_entries()
    from mage.agents.decomposition import ArchitectureSpec
    arch = ArchitectureSpec(parts=["api"], components=["auth-svc"], layers=["http"])

    output = render_plan(entries, ascertain, arch, template)

    assert output.startswith("---\n")
    assert "behavior_ids:" in output
    assert "- 00000" in output
    assert "- 00001" in output


def test_render_plan_includes_behavior_sections(tmp_path):
    from mage.orchestration.plan_writer import render_plan
    template = tmp_path / "tpl.md"
    template.write_text(TEMPLATE, encoding="utf-8")
    ascertain = AscertainOutput(feature_id="f", feature_name="Auth", scope_statement="...")
    entries = _two_entries()
    from mage.agents.decomposition import ArchitectureSpec
    arch = ArchitectureSpec(parts=[], components=[], layers=[])

    output = render_plan(entries, ascertain, arch, template)

    assert "## Behaviors" in output
    assert "00000" in output
    assert "auth" in output
    assert "00001" in output
    assert "orders" in output
