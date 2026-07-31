from mage.orchestration.events import EventType


def test_plan7_event_type_members_exist():
    for name in (
        "SCENARIO_REVERTED_TO_INSCRIBING",
        "SCENARIO_REVISION_REQUESTED",
        "SCENARIO_SUPERSESSION_REQUESTED",
        "SCENARIO_DEPRECATED",
    ):
        assert hasattr(EventType, name), f"EventType.{name} missing"


def test_event_type_values_unique():
    values = [m.value for m in EventType]
    assert len(values) == len(set(values)), "duplicate EventType values"
