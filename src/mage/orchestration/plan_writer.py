"""Plan writer: renders plan.md from behaviors + Ascertain output + architecture + template."""

from __future__ import annotations

from pathlib import Path

import yaml

from mage.agents.decomposition import ArchitectureSpec
from mage.artifacts.ascertain import AscertainOutput
from mage.artifacts.mapping import BaseBIDEntry


def _behavior_ids_yaml(entries: list[BaseBIDEntry]) -> str:
    lines = []
    for e in entries:
        lines.append(f"  - {e.base_bid}")
    return "\n".join(lines)


def _behaviors_yaml(entries: list[BaseBIDEntry]) -> str:
    data = []
    for e in entries:
        data.append({
            "id": e.base_bid,
            "name": e.behavior_name,
            "depends_on": e.depends_on,
            "notes": e.notes,
        })
    return yaml.safe_dump(data, sort_keys=False).rstrip()


def _architecture_summary(arch: ArchitectureSpec) -> str:
    parts = ", ".join(arch.parts) if arch.parts else "(none)"
    components = ", ".join(arch.components) if arch.components else "(none)"
    layers = ", ".join(arch.layers) if arch.layers else "(none)"
    return f"- **Parts:** {parts}\n- **Components:** {components}\n- **Layers:** {layers}"


def _behavior_sections(entries: list[BaseBIDEntry]) -> str:
    sections = []
    for e in entries:
        deps = ", ".join(e.depends_on) if e.depends_on else "(none)"
        cross = ", ".join(e.cross_behavior_links) if e.cross_behavior_links else "(none)"
        section = (
            f"### {e.base_bid} — {e.behavior_name}\n\n"
            f"**Description:** {e.behavior_description}\n\n"
            f"**Depends on:** {deps}\n\n"
            f"**Notes:** {e.notes or '(none)'}\n\n"
            f"**Cross-behavior links:** {cross}\n"
        )
        sections.append(section)
    return "\n".join(sections)


def render_plan(
    entries: list[BaseBIDEntry],
    ascertain: AscertainOutput,
    architecture: ArchitectureSpec,
    template_path: Path,
) -> str:
    """Render plan.md content from behaviors, Ascertain output, architecture, and template."""
    template = template_path.read_text(encoding="utf-8")
    return template.format(
        behavior_ids_yaml=_behavior_ids_yaml(entries),
        behaviors_yaml=_behaviors_yaml(entries),
        project_id=ascertain.feature_id,
        feature_name=ascertain.feature_name,
        scope_statement=ascertain.scope_statement,
        architecture_summary=_architecture_summary(architecture),
        behavior_sections=_behavior_sections(entries),
    )
