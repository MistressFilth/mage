"""InspectLoopStage: one pass of per-increment Inspect (mechanical + reviewer).

Plan 6: this stage is no longer a StageNode. `inspect_increment` is the
single entry point. It returns the routing decision so `FeatureRunner` can
decide whether to re-loop, halt, or break. The mechanical pre-check, the
reviewer call, the journal append, and the cosmetic queue are all in here.
Route detection is now an explicit field on the finding (Task 6) — no more
string-prefix parsing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from mage.artifacts.inspect import CosmeticItem, InspectJournalEntry
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext
from mage.orchestration.runner import Increment, IncrementResult, ScenarioTarget
from mage.verification.host_overrides import HostConfig

InspectRoute = Literal["spec", "code", "cosmetic"]


def _normalize_mechanical_findings(items) -> list:
    """Plan 4 introduced an adapter for the (CheckResult | MechanicalFinding)
    return shape. Kept here verbatim so the new file builds the same contract."""
    out = []
    for item in items:
        finding_id = getattr(item, "finding_id", None) or getattr(item, "id", None)
        if finding_id is None:
            continue
        out.append(item)
    return out


class InspectLoopStage:
    """One increment of Inspect. Returns the routing decision."""

    def __init__(
        self,
        events_log: EventsLog,
        *,
        mechanical_verifier,
        increment_quality_reviewer,
        host_config: HostConfig,
    ) -> None:
        self.events_log = events_log
        self.mechanical_verifier = mechanical_verifier
        self.increment_quality_reviewer = increment_quality_reviewer
        self.host_config = host_config

    async def inspect_increment(
        self,
        context: PipelineContext,
        *,
        target: ScenarioTarget,
        increment: Increment,
        result: IncrementResult,
    ) -> InspectRoute | None:
        """Run mechanical, then the increment-quality reviewer, then journal.

        Returns:
            "spec" — the runner halts via ScenarioInspectHalted.
            "code" — the runner re-loops with this finding in carry-forward.
            None   — clean OR cosmetic-only (cosmetic is queued, not re-looped).
        """
        await self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_LOOP_STARTED,
                payload={
                    "sub_bid": target.sub_bid,
                    "scenario_name": target.scenario_name,
                    "increment_id": f"{target.sub_bid}-{context.iteration}",
                },
            )
        )
        iteration = context.iteration
        if iteration > self.host_config.per_loop_max_iterations:
            from mage.orchestration.etch import ScenarioInspectHalted

            raise ScenarioInspectHalted(
                f"per-loop budget exhausted for sub-bid {target.sub_bid!r}"
            )

        # 1. Mechanical pre-check
        raw_mech = self.mechanical_verifier.verify(scope="increment")
        for f in _normalize_mechanical_findings(raw_mech):
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_JOURNAL_APPENDED,
                    payload={
                        "sub_bid": target.sub_bid,
                        "dimension": "mechanical",
                        "severity": getattr(f, "severity", "minor"),
                        "route": "code",
                        "finding_id": getattr(f, "finding_id", "?"),
                        "location": getattr(f, "location", "?"),
                        "issue": getattr(f, "issue", "?"),
                        "rationale": getattr(f, "rationale", ""),
                        "iteration": iteration,
                    },
                )
            )
            context.mapping = context.mapping.append_inspect_journal(
                target.sub_bid,
                InspectJournalEntry(
                    timestamp=datetime.now(UTC),
                    iteration=iteration,
                    dimension="mechanical",
                    severity=getattr(f, "severity", "minor"),
                    route="code",
                    finding_id=getattr(f, "finding_id", "?"),
                    location=getattr(f, "location", "?"),
                    issue=getattr(f, "issue", "?"),
                    rationale=getattr(f, "rationale", ""),
                ),
            )

        # 2. IncrementQualityReviewer
        recent_window = [
            InspectJournalEntry.model_validate(e)
            for e in context.mapping.inspect_journal.get(target.sub_bid, [])[-5:]
        ]
        verdict = await self.increment_quality_reviewer.run(
            increment_diff=result.diff,
            new_test=increment.red_test_code,
            scenario_steps=target.steps,
            recent_journal_window=recent_window,
        )
        if not verdict.findings:
            return None

        # 3. Route findings. Route is now an explicit field; no prefix parsing.
        spec_route: InspectRoute | None = None
        spec_finding = None
        code_count = 0
        for f in verdict.findings:
            route: InspectRoute = f.route
            if route == "spec":
                spec_route = "spec"
                # Track the first spec-route finding so the emit below can
                # quote its issue text. Latest finding wins if the reviewer
                # emits multiple spec findings on the same increment.
                spec_finding = f
            elif route == "code":
                code_count += 1
            elif route == "cosmetic":
                context.mapping = context.mapping.append_cosmetic(
                    "unknown",
                    CosmeticItem(
                        sub_bid=target.sub_bid,
                        scenario_name=target.scenario_name,
                        location=f.location,
                        text=f.suggestion,
                        proposed_by="increment_quality",
                    ),
                )

            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_JOURNAL_APPENDED,
                    payload={
                        "sub_bid": target.sub_bid,
                        "dimension": getattr(verdict, "dimension", "increment_quality"),
                        "severity": f.severity,
                        "route": route,
                        "finding_id": f.id,
                        "location": f.location,
                        "issue": f.issue,
                        "rationale": "",
                        "iteration": iteration,
                    },
                )
            )
            context.mapping = context.mapping.append_inspect_journal(
                target.sub_bid,
                InspectJournalEntry(
                    timestamp=datetime.now(UTC),
                    iteration=iteration,
                    dimension=getattr(verdict, "dimension", "increment_quality"),
                    severity=f.severity,
                    route=route,
                    finding_id=f.id,
                    location=f.location,
                    issue=f.issue,
                    rationale="",
                ),
            )

        if spec_route == "spec":
            # Emit a SCENARIO_REVISION_REQUESTED event before returning the
            # route so the DisciplineStage handler can call begin_revision.
            # The runner (or the graph shim) translates this "spec" route
            # into ScenarioInspectHalted; the event is the discipline hook
            # for that halt path.
            reason = (
                getattr(spec_finding, "issue", None)
                if spec_finding is not None
                else "spec-route finding"
            )
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SCENARIO_REVISION_REQUESTED,
                    payload={
                        "sub_bid": target.sub_bid,
                        "reason": str(reason) if reason else "spec-route finding",
                        "originating_stage": "inspect_loop",
                    },
                )
            )
            return "spec"
        if code_count:
            return "code"
        return None
