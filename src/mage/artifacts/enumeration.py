"""Behavior enumeration: validates dependencies, detects cycles, assigns base BIDs."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import yaml as _yaml
from pydantic import BaseModel, ConfigDict, Field

from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact
from mage.orchestration.events import Event, EventsLog, EventType


class BehaviorSpec(BaseModel):
    """Decomposition agent's structured output for one behavior (no BID)."""

    model_config = ConfigDict(frozen=True)
    name: str
    description: str
    depends_on: list[str] = Field(default_factory=list)
    notes: str = ""
    cross_behavior_links: list[str] = Field(default_factory=list)


class BehaviorEnumerationError(Exception):
    """Base class for behavior enumeration errors."""


class BehaviorDependencyError(BehaviorEnumerationError):
    """Raised when a behavior's depends_on references an unknown behavior."""


class BehaviorDependencyCycleError(BehaviorEnumerationError):
    """Raised when behaviors have a dependency cycle."""


class DuplicateBehaviorNameError(BehaviorEnumerationError):
    """Raised when two behaviors share the same name within one enumeration."""


class NoBehaviorsError(BehaviorEnumerationError):
    """Raised when an enumeration has zero behaviors."""


class CrossBehaviorLinkError(BehaviorEnumerationError):
    """Raised when a cross_behavior_links entry references an unknown behavior."""


def _topological_sort(
    specs: list[BehaviorSpec],
) -> list[BehaviorSpec]:
    """Sort specs in dependency order. Raises on cycle.

    Input is a list of BehaviorSpec. Each spec's depends_on refers to other
    specs by name. Output is the same specs in an order where each spec's
    dependencies come before it.
    """
    by_name = {s.name: s for s in specs}
    visited: set[str] = set()
    visiting: set[str] = set()
    result: list[BehaviorSpec] = []

    def visit(name: str, path: list[str]) -> None:
        if name in visited:
            return
        if name in visiting:
            cycle = " -> ".join(path + [name])
            raise BehaviorDependencyCycleError(f"Dependency cycle: {cycle}")
        spec = by_name.get(name)
        if spec is None:
            return  # external dependency, resolved elsewhere
        visiting.add(name)
        for dep in spec.depends_on:
            visit(dep, path + [name])
        visiting.remove(name)
        visited.add(name)
        result.append(spec)

    for spec in specs:
        visit(spec.name, [])

    return result


async def enumerate_behaviors(
    behavior_specs: list[BehaviorSpec],
    mapping: MappingArtifact,
    project_dir: Path | None = None,
    events_log: EventsLog | None = None,
    feature_id: str = "",
) -> tuple[MappingArtifact, Path] | list[BaseBIDEntry]:
    """Validate behavior specs, assign base BIDs, and write files atomically.

    When ``project_dir`` and ``events_log`` are provided, writes
    ``behaviors.yaml`` and updates ``mapping.yaml``, emits a
    ``BEHAVIORS_ENUMERATED`` event, and returns ``(updated_mapping,
    behaviors_yaml_path)``.

    The legacy two-argument form returns the new entries without writing files;
    it is retained for callers from the previous enumeration interface.

    Raises BehaviorEnumerationError subclasses on validation failure; in that
    case no files are written.
    """
    if not behavior_specs:
        raise NoBehaviorsError("Cannot enumerate zero behaviors")

    if (project_dir is None) != (events_log is None):
        raise TypeError("project_dir and events_log must be provided together")

    names = [s.name for s in behavior_specs]
    if len(names) != len(set(names)):
        counts = Counter(names)
        duplicates = [n for n, c in counts.items() if c > 1]
        raise DuplicateBehaviorNameError(f"Duplicate behavior names: {duplicates}")

    existing_name_to_bid = {e.behavior_name: e.base_bid for e in mapping.base_bids}
    existing_bids = set(existing_name_to_bid.values())
    pending_names = set(names)

    for spec in behavior_specs:
        for dep in spec.depends_on:
            if dep in pending_names:
                continue
            if dep in existing_name_to_bid:
                continue
            if dep in existing_bids:
                continue
            raise BehaviorDependencyError(
                f"Behavior '{spec.name}' has unresolvable dependency: '{dep}'"
            )
        for link in spec.cross_behavior_links:
            if link in pending_names:
                continue
            if link in existing_name_to_bid:
                continue
            if link in existing_bids:
                continue
            raise CrossBehaviorLinkError(
                f"Behavior '{spec.name}' has unresolvable cross_behavior_link: '{link}'"
            )

    sorted_specs = _topological_sort(behavior_specs)

    pending_to_bid: dict[str, str] = {}
    entries: list[BaseBIDEntry] = []
    current = mapping.next_base_bid()

    for spec in sorted_specs:
        pending_to_bid[spec.name] = current.value
        resolved_depends = [
            pending_to_bid[dep]
            if dep in pending_to_bid
            else existing_name_to_bid.get(dep, dep)
            for dep in spec.depends_on
        ]
        resolved_cross = [
            pending_to_bid[link]
            if link in pending_to_bid
            else existing_name_to_bid.get(link, link)
            for link in spec.cross_behavior_links
        ]
        entry = BaseBIDEntry(
            base_bid=current.value,
            behavior_name=spec.name,
            behavior_description=spec.description,
            depends_on=resolved_depends,
            notes=spec.notes,
            cross_behavior_links=resolved_cross,
            behavior_halt=[],
        )
        entries.append(entry)
        current = current.increment()

    if project_dir is None:
        return entries
    assert events_log is not None

    project_dir = Path(project_dir)

    # Build updated mapping without mutating the input.
    updated_mapping = mapping.model_copy(
        update={"base_bids": list(mapping.base_bids) + entries}
    )

    # Write behaviors.yaml atomically.
    behaviors_data = {
        "schema_version": 1,
        "feature_id": feature_id,
        "enumerated_at": datetime.now(UTC).isoformat(),
        "behaviors": [
            {
                "id": e.base_bid,
                "name": e.behavior_name,
                "description": e.behavior_description,
                "depends_on": e.depends_on,
                "notes": e.notes,
                "cross_behavior_links": e.cross_behavior_links,
            }
            for e in entries
        ],
    }
    behaviors_path = project_dir / "behaviors.yaml"
    behaviors_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = behaviors_path.with_suffix(behaviors_path.suffix + ".tmp")
    tmp.write_text(_yaml.safe_dump(behaviors_data, sort_keys=False), encoding="utf-8")
    tmp.replace(behaviors_path)

    # Write updated mapping atomically.
    await updated_mapping.save(project_dir / "mapping.yaml")

    await events_log.append(
        Event(
            timestamp=datetime.now(UTC),
            event_type=EventType.BEHAVIORS_ENUMERATED,
            payload={
                "count": len(entries),
                "behaviors_yaml_path": str(behaviors_path),
            },
        )
    )

    return updated_mapping, behaviors_path
