"""Behavior enumeration: validates dependencies, detects cycles, assigns base BIDs."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from mage.artifacts.mapping import BaseBIDEntry, MappingArtifact


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


def enumerate_behaviors(
    behavior_specs: list[BehaviorSpec],
    mapping: MappingArtifact,
) -> list[BaseBIDEntry]:
    """Validate behavior specs and assign base BIDs.

    Returns a list of new BaseBIDEntry objects (one per spec) with BIDs assigned
    in topological order. The mapping is read but not modified — the caller is
    responsible for appending the entries and saving.
    """
    if not behavior_specs:
        raise NoBehaviorsError("Cannot enumerate zero behaviors")

    # Check for duplicate names
    names = [s.name for s in behavior_specs]
    if len(names) != len(set(names)):
        counts = Counter(names)
        duplicates = [n for n, c in counts.items() if c > 1]
        raise DuplicateBehaviorNameError(f"Duplicate behavior names: {duplicates}")

    # Build resolvers: name -> base-BID for both existing and pending behaviors
    existing_name_to_bid = {e.behavior_name: e.base_bid for e in mapping.base_bids}
    existing_bids = set(existing_name_to_bid.values())
    pending_names = set(names)

    # Validate that every depends_on resolves
    for spec in behavior_specs:
        for dep in spec.depends_on:
            if dep in pending_names:
                continue  # pending behavior, resolved by name
            if dep in existing_name_to_bid:
                continue  # existing behavior_name
            if dep in existing_bids:
                continue  # existing base-BID
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

    # Topological sort
    sorted_specs = _topological_sort(behavior_specs)

    # Assign BIDs in topological order
    pending_to_bid: dict[str, str] = {}
    entries: list[BaseBIDEntry] = []
    current = mapping.next_base_bid()
    for spec in sorted_specs:
        pending_to_bid[spec.name] = current.value

        # Resolve dependencies and cross links to base-BID strings
        resolved_depends = []
        for dep in spec.depends_on:
            if dep in pending_to_bid:
                resolved_depends.append(pending_to_bid[dep])
            elif dep in existing_name_to_bid:
                resolved_depends.append(existing_name_to_bid[dep])
            else:
                # Existing base-BID
                resolved_depends.append(dep)

        resolved_cross = []
        for link in spec.cross_behavior_links:
            if link in pending_to_bid:
                resolved_cross.append(pending_to_bid[link])
            elif link in existing_name_to_bid:
                resolved_cross.append(existing_name_to_bid[link])
            else:
                resolved_cross.append(link)

        entry = BaseBIDEntry(
            base_bid=current.value,
            behavior_name=spec.name,
            behavior_description=spec.description,
            depends_on=resolved_depends,
            notes=spec.notes,
            cross_behavior_links=resolved_cross,
        )
        entries.append(entry)
        current = current.increment()

    return entries
