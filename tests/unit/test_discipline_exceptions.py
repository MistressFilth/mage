from mage.orchestration.exceptions import (
    CycleAlreadyInProgress,
    DecompositionOpen,
    DisciplineViolation,
    ForwardOrderViolation,
    ModelCannotApplyCosmetic,
    NotApprovedForAutomation,
)


def test_all_subclass_discipline_violation():
    for cls in (
        ForwardOrderViolation,
        CycleAlreadyInProgress,
        NotApprovedForAutomation,
        DecompositionOpen,
        ModelCannotApplyCosmetic,
    ):
        assert issubclass(cls, DisciplineViolation)


def test_subclasses_carry_message():
    err = ForwardOrderViolation("scenario 1 still inscribing")
    assert isinstance(err, DisciplineViolation)
    assert "still inscribing" in str(err)
