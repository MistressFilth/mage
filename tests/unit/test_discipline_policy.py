# tests/unit/test_discipline_policy.py — P1 section
from mage.artifacts.mapping import (
    BaseBIDEntry,
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.orchestration.discipline.policy import assert_independent_gates
from mage.orchestration.exceptions import ForwardOrderViolation
import pytest


def _scenario(sub_bid: str, status: LifecycleStatus) -> ScenarioEntry:
    return ScenarioEntry(sub_bid=sub_bid, scenario_text_hash="h", lifecycle_status=status)


def _mapping(scenarios: list[ScenarioEntry]) -> MappingArtifact:
    return MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(
                base_bid="00000",
                behavior_name="b",
                behavior_description="d",
                scenarios=scenarios,
            )
        ],
    )


def test_p1_passes_when_earlier_live():
    m = _mapping([_scenario("A", LifecycleStatus.LIVE), _scenario("B", LifecycleStatus.INSCRIBING)])
    assert_independent_gates(m, "B")  # no raise


def test_p1_passes_when_earlier_deprecated():
    m = _mapping([_scenario("A", LifecycleStatus.DEPRECATED), _scenario("B", LifecycleStatus.INSCRIBING)])
    assert_independent_gates(m, "B")  # no raise


def test_p1_raises_when_earlier_inscribing():
    m = _mapping([_scenario("A", LifecycleStatus.INSCRIBING), _scenario("B", LifecycleStatus.INSCRIBING)])
    with pytest.raises(ForwardOrderViolation):
        assert_independent_gates(m, "B")


def test_p1_raises_when_earlier_approved():
    m = _mapping([_scenario("A", LifecycleStatus.APPROVED), _scenario("B", LifecycleStatus.INSCRIBING)])
    with pytest.raises(ForwardOrderViolation):
        assert_independent_gates(m, "B")


def test_p1_respects_base_bid_ordering():
    # Scenario "B" in base_bid 00000 declared after "A" in 00001; A must be live first.
    m = MappingArtifact(
        project_id="p",
        base_bids=[
            BaseBIDEntry(base_bid="00001", behavior_name="b1", behavior_description="d1",
                         scenarios=[_scenario("A", LifecycleStatus.INSCRIBING)]),
            BaseBIDEntry(base_bid="00000", behavior_name="b0", behavior_description="d0",
                         scenarios=[_scenario("B", LifecycleStatus.INSCRIBING)]),
        ],
    )
    with pytest.raises(ForwardOrderViolation):
        assert_independent_gates(m, "B")
