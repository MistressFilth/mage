"""Discipline enforcement exception hierarchy.

All Three Practices gate failures raise subclasses of DisciplineViolation.
Distinguishing the failure type lets DisciplineStage emit a precise event
instead of a generic halt.
"""

from __future__ import annotations


class DisciplineViolation(Exception):
    """Base for all Three Practices gate failures."""


class ForwardOrderViolation(DisciplineViolation):
    """P1 / P3 / P4: scenario attempted to start before its predecessor completed."""


class CycleAlreadyInProgress(DisciplineViolation):
    """P2: another scenario's cycle already holds the cycle lock."""


class NotApprovedForAutomation(DisciplineViolation):
    """P3: scenario attempted Etch/Realize entry without APPROVED status."""


class DecompositionOpen(DisciplineViolation):
    """P4: per-scenario cycle started before Decomposition closed."""


class ModelCannotApplyCosmetic(DisciplineViolation):
    """Cosmetic gate: model attempted to apply a live-scenario text change."""


class StageHalted(Exception):
    """Raised by a stage to stop the pipeline cleanly without an error.

    The graph runner catches this, emits HALT_PERSISTED with the carried
    reason, and exits with status 0. Use for control-flow halts (e.g. the
    Plan 15 approval gate) where the run ended by design, not by failure.
    """

    def __init__(
        self,
        reason: str,
        originating_stage: str = "decomposition",
        affected_behaviors: list[str] | None = None,
        **context: object,
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.originating_stage = originating_stage
        self.affected_behaviors = list(affected_behaviors) if affected_behaviors else []
        self.context = dict(context)
