"""Tests for Inscribe agent models."""


def test_scenario_spec_minimal():
    from mage.agents.inscribe import ScenarioSpec

    spec = ScenarioSpec(name="login succeeds", gherkin_body="Given ...")
    assert spec.name == "login succeeds"
    assert spec.gherkin_body == "Given ..."
    assert spec.tags == []
    assert spec.notes == ""
    assert spec.cross_behavior_tags == []


def test_scenario_spec_with_all_fields():
    from mage.agents.inscribe import ScenarioSpec

    spec = ScenarioSpec(
        name="register duplicate email fails",
        gherkin_body="Given a registered email\nWhen register\nThen fail",
        tags=["@auth", "@negative"],
        notes="Edge case; needs user-fixture cleanup.",
        cross_behavior_tags=["00000@authenticate-user"],
    )
    assert spec.tags == ["@auth", "@negative"]
    assert spec.cross_behavior_tags == ["00000@authenticate-user"]


def test_scenario_spec_is_frozen():
    from pydantic import ValidationError

    from mage.agents.inscribe import ScenarioSpec

    spec = ScenarioSpec(name="x", gherkin_body="y")
    import pytest

    with pytest.raises(ValidationError):
        spec.name = "mutated"  # ty: ignore[invalid-assignment]


def test_inscribe_output_holds_scenarios():
    from mage.agents.inscribe import InscribeOutput, ScenarioSpec

    scenarios = [
        ScenarioSpec(name="a", gherkin_body="A"),
        ScenarioSpec(name="b", gherkin_body="B"),
    ]
    output = InscribeOutput(scenarios=scenarios)
    assert len(output.scenarios) == 2
    assert output.scenarios[0].name == "a"
