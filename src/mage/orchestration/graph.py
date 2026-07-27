"""PipelineGraph: linear stage runner for the orchestration state machine.

This task establishes the basic shape: a PipelineGraph runs a list of stages
in order, threading a PipelineContext through them. The actual Pydantic-Graph
node traversal is deferred to Plan 6 (Three Practices + Concurrency Enforcement),
which wires in the full async runner. For Plan 1, the runner is a plain linear
iteration that uses StageNode.run() per stage.
"""

from __future__ import annotations

from mage.orchestration.events import EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode


class PipelineGraph:
    """Runs a list of stages in order, threading PipelineContext through them."""

    def __init__(self, stages: list[StageNode], events_log: EventsLog) -> None:
        self.events_log = events_log
        self.stages = list(stages)

    def run(self, initial_context: PipelineContext) -> PipelineContext:
        """Synchronously run the graph, threading context through stages.

        For Plan 1, runs stages directly (not via Pydantic-Graph's async runner).
        Plan 6 will wire in the full async runner for cross-cutting discipline.
        """
        context = initial_context
        for stage in self.stages:
            context = stage.run(context)
        return context