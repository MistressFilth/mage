"""Tests for behavior enumeration: validation, cycle detection, BID assignment."""

from __future__ import annotations

import pytest

from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import MappingArtifact


def _spec(name: str, *, depends_on=(), cross=()) -> "BehaviorSpec":
    from mage.artifacts.enumeration import BehaviorSpec
    return BehaviorSpec(
        name=name,
        description=f"{name} behavior",
        depends_on=list(depends_on),
        cross_behavior_links=list(cross),
    )


@pytest.mark.asyncio
async def test_assign_bids_monotonically_to_empty_mapping():
    from mage.artifacts.enumeration import enumerate_behaviors
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth"), _spec("orders", depends_on=["auth"]), _spec("payments", depends_on=["orders"])]
    entries = await enumerate_behaviors(specs, mapping)
    assert [e.base_bid for e in entries] == ["00000", "00001", "00002"]


@pytest.mark.asyncio
async def test_assign_bids_continues_from_existing_mapping():
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import BaseBIDEntry
    existing = BaseBIDEntry(base_bid="00004", behavior_name="seed", behavior_description="seed")
    mapping = MappingArtifact(project_id="p", base_bids=[existing])
    specs = [_spec("auth"), _spec("orders")]
    entries = await enumerate_behaviors(specs, mapping)
    assert [e.base_bid for e in entries] == ["00005", "00006"]


@pytest.mark.asyncio
async def test_dependency_resolves_to_pending_behavior():
    from mage.artifacts.enumeration import enumerate_behaviors
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("orders", depends_on=["auth"]), _spec("auth")]
    entries = await enumerate_behaviors(specs, mapping)
    # auth comes first because orders depends on it
    auth_entry = next(e for e in entries if e.behavior_name == "auth")
    orders_entry = next(e for e in entries if e.behavior_name == "orders")
    assert auth_entry.base_bid < orders_entry.base_bid
    assert orders_entry.depends_on == [auth_entry.base_bid]


@pytest.mark.asyncio
async def test_unresolvable_dependency_raises():
    from mage.artifacts.enumeration import enumerate_behaviors, BehaviorDependencyError
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("orders", depends_on=["nonexistent"])]
    with pytest.raises(BehaviorDependencyError):
        await enumerate_behaviors(specs, mapping)


@pytest.mark.asyncio
async def test_cycle_in_dependencies_raises():
    from mage.artifacts.enumeration import enumerate_behaviors, BehaviorDependencyCycleError
    mapping = MappingArtifact(project_id="p")
    specs = [
        _spec("a", depends_on=["b"]),
        _spec("b", depends_on=["a"]),
    ]
    with pytest.raises(BehaviorDependencyCycleError):
        await enumerate_behaviors(specs, mapping)


@pytest.mark.asyncio
async def test_self_referential_dependency_caught_as_cycle():
    from mage.artifacts.enumeration import enumerate_behaviors, BehaviorDependencyCycleError
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("a", depends_on=["a"])]
    with pytest.raises(BehaviorDependencyCycleError):
        await enumerate_behaviors(specs, mapping)


@pytest.mark.asyncio
async def test_duplicate_behavior_names_raise():
    from mage.artifacts.enumeration import enumerate_behaviors, DuplicateBehaviorNameError
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth"), _spec("auth")]
    with pytest.raises(DuplicateBehaviorNameError):
        await enumerate_behaviors(specs, mapping)


@pytest.mark.asyncio
async def test_empty_behavior_list_raises():
    from mage.artifacts.enumeration import enumerate_behaviors, NoBehaviorsError
    mapping = MappingArtifact(project_id="p")
    with pytest.raises(NoBehaviorsError):
        await enumerate_behaviors([], mapping)


@pytest.mark.asyncio
async def test_cross_behavior_link_to_existing_behavior():
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import BaseBIDEntry
    existing = BaseBIDEntry(base_bid="00010", behavior_name="payments", behavior_description="payments")
    mapping = MappingArtifact(project_id="p", base_bids=[existing])
    specs = [_spec("checkout", cross=["payments"])]
    entries = await enumerate_behaviors(specs, mapping)
    assert entries[0].cross_behavior_links == ["00010"]


@pytest.mark.asyncio
async def test_cross_behavior_link_to_pending_behavior():
    from mage.artifacts.enumeration import enumerate_behaviors
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("a"), _spec("b", cross=["a"])]
    entries = await enumerate_behaviors(specs, mapping)
    b = next(e for e in entries if e.behavior_name == "b")
    a = next(e for e in entries if e.behavior_name == "a")
    assert b.cross_behavior_links == [a.base_bid]


@pytest.mark.asyncio
async def test_enumerate_writes_behaviors_yaml(tmp_path):
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog, EventType
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth"), _spec("orders", depends_on=["auth"])]

    updated_mapping, behaviors_path = await enumerate_behaviors(specs, mapping, project_dir=tmp_path, events_log=log)

    assert behaviors_path.exists()
    assert behaviors_path == tmp_path / "behaviors.yaml"
    import yaml
    data = yaml.safe_load(behaviors_path.read_text())
    assert data["schema_version"] == 1
    assert len(data["behaviors"]) == 2
    assert {b["name"] for b in data["behaviors"]} == {"auth", "orders"}


@pytest.mark.asyncio
async def test_enumerate_writes_updated_mapping(tmp_path):
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth")]

    updated_mapping, _ = await enumerate_behaviors(specs, mapping, project_dir=tmp_path, events_log=log)

    assert len(updated_mapping.base_bids) == 1
    assert updated_mapping.base_bids[0].behavior_name == "auth"


@pytest.mark.asyncio
async def test_enumerate_emits_behaviors_enumerated_event(tmp_path):
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog, EventType
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth")]

    await enumerate_behaviors(specs, mapping, project_dir=tmp_path, events_log=log)

    events = log.read_all()
    enum_events = [e for e in events if e.event_type == EventType.BEHAVIORS_ENUMERATED]
    assert len(enum_events) == 1
    assert enum_events[0].payload["count"] == 1


@pytest.mark.asyncio
async def test_enumerate_writes_feature_id_from_caller(tmp_path):
    from mage.artifacts.enumeration import enumerate_behaviors
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    import yaml as _yaml
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth")]
    await enumerate_behaviors(
        specs, mapping, project_dir=tmp_path, events_log=log, feature_id="feat-001"
    )
    data = _yaml.safe_load((tmp_path / "behaviors.yaml").read_text())
    assert data["feature_id"] == "feat-001"


@pytest.mark.asyncio
async def test_enumerate_does_not_write_on_validation_error(tmp_path):
    from mage.artifacts.enumeration import enumerate_behaviors, DuplicateBehaviorNameError
    from mage.artifacts.mapping import MappingArtifact
    from mage.orchestration.events import EventsLog
    log = EventsLog(tmp_path / "events.jsonl")
    mapping = MappingArtifact(project_id="p")
    specs = [_spec("auth"), _spec("auth")]

    with pytest.raises(DuplicateBehaviorNameError):
        await enumerate_behaviors(specs, mapping, project_dir=tmp_path, events_log=log)

    assert not (tmp_path / "behaviors.yaml").exists()
