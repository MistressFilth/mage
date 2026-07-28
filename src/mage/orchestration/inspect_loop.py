"""InspectLoop stage: per-scenario per-increment Inspect (mechanical + IncrementQuality)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from mage.artifacts.inspect import CosmeticItem, InspectJournalEntry
from mage.orchestration.etch import ScenarioInspectHalted
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.verification.host_overrides import HostConfig

if TYPE_CHECKING:
    from mage.orchestration.realize import RealizeStage


class InspectLoopStage(StageNode):
    """Per-scenario per-increment Inspect.

    Per spec R19 / R20 / GC-5:
    - Mechanical pre-check first (4 checks; Plan 4 uses Plan 1's MechanicalVerifier
      with the relevant subset). On fail: increment iteration, return to Realize.
    - IncrementQualityReviewer second. Routes findings via R20:
      - spec-route: halt unconditionally (raises ScenarioInspectHalted)
      - code-route: log to journal, continue (no iteration increment)
      - cosmetic-route: log to journal + cosmetic queue, continue
    - All-pass: emit INSPECT_LOOP_PASSED, advance.
    """

    name = "inspect_loop"

    def __init__(
        self,
        events_log: EventsLog,
        mechanical_verifier,
        increment_quality_reviewer,
        host_config: HostConfig,
        realize_stage: RealizeStage | None = None,
    ) -> None:
        super().__init__(events_log)
        self.mechanical_verifier = mechanical_verifier
        self.increment_quality_reviewer = increment_quality_reviewer
        self.host_config = host_config
        self.realize_stage = realize_stage

    def _run(self, context: PipelineContext) -> PipelineContext:
        # Plan 4 stub: emit INSPECT_LOOP_COMPLETED. The per-increment loop is
        # orchestrated by the calling driver (RealizeStage or external script).
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_LOOP_COMPLETED,
                payload={"stub": True},
            )
        )
        return context

    def _run_single_increment(
        self,
        context: PipelineContext,
        *,
        sub_bid: str,
        base_bid: str = "00000",
        scenario_name: str = "stub",
        increment_diff: str,
        new_test: str,
        scenario_steps: list[str],
    ) -> None:
        """Per spec R19 / R20: mechanical first, then IncrementQuality, then R20 routing."""
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_LOOP_STARTED,
                payload={
                    "sub_bid": sub_bid,
                    "scenario_name": scenario_name,
                    "increment_id": f"{sub_bid}-{context.iteration}",
                },
            )
        )

        # 1. Mechanical pre-check
        mech_findings = self.mechanical_verifier.run(scope="increment")
        if mech_findings:
            iteration = context.iteration + 1
            for f in mech_findings:
                self.events_log.append(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.INSPECT_JOURNAL_APPENDED,
                        payload={
                            "sub_bid": sub_bid,
                            "dimension": "mechanical",
                            "severity": f.severity,
                            "route": "code",
                            "finding_id": f.check,
                            "location": f.location,
                            "issue": f.issue,
                            "rationale": f.rationale,
                            "iteration": iteration,
                        },
                    )
                )
            context.iteration = iteration
            if iteration >= self.host_config.per_loop_max_iterations:
                self.events_log.append(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.SCENARIO_HALT_PERSISTED,
                        payload={
                            "base_bid": base_bid,
                            "scenario_name": scenario_name,
                            "sub_bid": sub_bid,
                            "iteration": iteration,
                            "reason": "mechanical_budget_overflow",
                        },
                    )
                )
                raise ScenarioInspectHalted(
                    base_bid=base_bid,
                    scenario_name=scenario_name,
                    sub_bid=sub_bid,
                    iteration=iteration,
                )
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_LOOP_FAILED,
                    payload={"sub_bid": sub_bid, "findings_count": len(mech_findings)},
                )
            )
            return  # return to Realize

        # 2. IncrementQualityReviewer
        recent_window = [
            InspectJournalEntry.model_validate(e)
            for e in context.mapping.inspect_journal.get(sub_bid, [])[-5:]
        ]
        verdict = self.increment_quality_reviewer.run(
            increment_diff=increment_diff,
            new_test=new_test,
            scenario_steps=scenario_steps,
            recent_journal_window=recent_window,
        )

        # 3. R20 routing
        route_breakdown: dict[str, int] = {"spec": 0, "code": 0, "cosmetic": 0}
        for f in verdict.findings:
            # Discover route: try attribute on f, then suggestion prefix, default to "code"
            route = getattr(f, "route", None)
            if route is None:
                # Fallback: parse from suggestion
                if f.suggestion.startswith("spec:"):
                    route = "spec"
                elif f.suggestion.startswith("cosmetic:"):
                    route = "cosmetic"
                else:
                    route = "code"
            route_breakdown[route] += 1
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_JOURNAL_APPENDED,
                    payload={
                        "sub_bid": sub_bid,
                        "dimension": verdict.dimension,
                        "severity": f.severity,
                        "route": route,
                        "finding_id": f.id,
                        "location": f.location,
                        "issue": f.issue,
                        "rationale": f.rationale,
                        "iteration": context.iteration,
                    },
                )
            )
            new_journal = context.mapping.append_inspect_journal(
                sub_bid,
                InspectJournalEntry(
                    timestamp=datetime.now(UTC),
                    iteration=context.iteration,
                    dimension=verdict.dimension,
                    severity=f.severity,
                    route=route,
                    finding_id=f.id,
                    location=f.location,
                    issue=f.issue,
                    rationale=f.rationale,
                ),
            )
            context.mapping = new_journal
            if route == "cosmetic":
                context.mapping = context.mapping.append_cosmetic(
                    CosmeticItem(
                        sub_bid=sub_bid,
                        scenario_name=scenario_name,
                        location=f.location,
                        text=f.suggestion or f.issue,
                        proposed_by=verdict.dimension,
                    )
                )

        # 4. Decision gate
        if route_breakdown["spec"] > 0:
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SCENARIO_HALT_PERSISTED,
                    payload={
                        "base_bid": base_bid,
                        "scenario_name": scenario_name,
                        "sub_bid": sub_bid,
                        "iteration": context.iteration,
                        "reason": "spec_route_finding",
                    },
                )
            )
            raise ScenarioInspectHalted(
                base_bid=base_bid,
                scenario_name=scenario_name,
                sub_bid=sub_bid,
                iteration=context.iteration,
            )

        # All routed to code/cosmetic or no findings → advance
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_LOOP_PASSED,
                payload={
                    "sub_bid": sub_bid,
                    "increment_id": f"{sub_bid}-{context.iteration}",
                    "route_breakdown": route_breakdown,
                },
            )
        )
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_LOOP_COMPLETED,
                payload={
                    "sub_bid": sub_bid,
                    "scenario_name": scenario_name,
                    "increment_id": f"{sub_bid}-{context.iteration}",
                    "route_breakdown": route_breakdown,
                },
            )
        )