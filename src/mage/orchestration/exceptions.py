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
