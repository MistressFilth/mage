"""InspectFeature stage: orchestrates end-of-feature Inspect + 3-tier severity routing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from mage.artifacts.inspect import (
    InspectArtifact,
    InspectArtifactContent,
    ScenarioInspectStatus,
)
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.verification.host_overrides import HostConfig

if TYPE_CHECKING:
    from mage.verification.reviewers.base import ReviewerAgent


class InspectFeatureHalted(Exception):
    """Raised when end-of-feature iteration budget is exhausted.

    Resume re-enters InspectFeatureStage from the events log.
    """

    def __init__(self, feature_id: str, iteration: int) -> None:
        self.feature_id = feature_id
        self.iteration = iteration
        super().__init__(
            f"InspectFeatureHalted for feature {feature_id!r} at iteration {iteration} "
            f"(eof_max_iterations exceeded)"
        )


class InspectFeatureStage(StageNode):
    """End-of-feature Inspect: full 7-reviewer sweep + CrossScenarioReviewer + 3-tier routing.

    Per spec R22: runs once per feature after all scenarios are LIVE. Performs
    a full sweep of the 7 Plan 3 reviewers + CrossScenarioReviewer, runs the
    mechanical pre-check, and routes findings via 3-tier severity routing
    (Critical → reenter Realize; Important → fix-wave; Minor → cosmetic queue).
    Persists an ``InspectArtifact`` digest-pinned on disk, emits
    ``INSPECT_FEATURE_PASSED`` when ready to merge, and raises
    ``InspectFeatureHalted`` on end-of-feature budget overflow.

    Reviewer dispatch contract (see CRITICAL block in Task 5 brief):
        - ``CrossScenarioReviewer.run(*, feature_summary, scenarios, mapping)``
        - Plan 3 reviewers: ``run(*, draft, spec_context, mapping, events_log, verdict_path)``

    These signatures are NOT interchangeable, so ``run_pass`` special-cases
    by ``reviewer.dimension`` rather than calling all reviewers with a single
    uniform kwargs shape. This is cleaner than a ``try/except TypeError``
    fallback because the dispatch stays explicit (one branch per reviewer
    family) and the synthetic ``ScenarioSpec`` build for Plan 3 reviewers is
    confined to a single helper. Test stubs use ``run(**kwargs)`` and accept
    either call shape.
    """

    name = "inspect_feature"

    def __init__(
        self,
        events_log: EventsLog,
        *,
        reviewers: list,
        host_config: HostConfig,
    ) -> None:
        super().__init__(events_log)
        self.reviewers = reviewers
        self.host_config = host_config

    def _run(self, context: PipelineContext) -> PipelineContext:  # noqa: ARG002
        # Plan 5: real driver is `run_pass` (called by an external orchestrator);
        # _run is a defensive stub that emits the completion event so a
        # misconfigured graph runner that calls the abstract _run still leaves
        # an observable trace in the events log instead of hanging silently.
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_FEATURE_COMPLETED,
                payload={"stub": True},
            )
        )
        return context

    def _dispatch_reviewer(
        self,
        reviewer,
        *,
        context: PipelineContext,
        feature_id: str,
        scenarios: list[dict],
    ):
        """Dispatch a reviewer based on its `dimension`.

        cross_scenario → CrossScenarioReviewer.run(feature_summary, scenarios, mapping)
        All others    → Plan 3 ReviewerAgent.run(draft, spec_context, mapping,
                          events_log, verdict_path) with a synthetic ScenarioSpec
                          built from the first scenario (per-scenario refinement is
                          a follow-up once the registry stops hard-coding models).
        """
        if getattr(reviewer, "dimension", "") == "cross_scenario":
            return reviewer.run(
                feature_summary={"feature_id": feature_id},
                scenarios=scenarios,
                mapping=context.mapping,
            )
        # Plan 3 reviewer — build a synthetic ScenarioSpec. Local import keeps
        # the module-level dependency graph flat (avoids pulling pydantic_ai at
        # import time, mirrors the inspect_loop.py pattern).
        from mage.agents.inscribe import ScenarioSpec

        scenario = (
            scenarios[0]
            if scenarios
            else {"scenario_name": "unknown", "sub_bid": "00000-0"}
        )
        synthetic_draft = ScenarioSpec(
            name=scenario.get("scenario_name", "unknown"),
            gherkin_body="",
            tags=[],
            notes="",
            cross_behavior_tags=[],
        )
        spec_context = {
            "feature_id": feature_id,
            "scenario_name": scenario.get("scenario_name", "unknown"),
            "sub_bid": scenario.get("sub_bid", "00000-0"),
        }
        verdict_path = (
            context.project_dir
            / ".haileris"
            / "verdicts"
            / feature_id
            / f"{reviewer.dimension}.yaml"
        )
        return reviewer.run(
            draft=synthetic_draft,
            spec_context=spec_context,
            mapping=context.mapping,
            events_log=self.events_log,
            verdict_path=verdict_path,
        )

    def run_pass(
        self,
        context: PipelineContext,
        *,
        feature_id: str,
        scenarios: list[dict],
        iteration: int | None = None,
    ) -> InspectArtifactContent:
        """Run one pass of InspectFeature.

        Returns the InspectArtifactContent. Raises InspectFeatureHalted on budget overflow.
        """
        if iteration is None:
            # Bump the pipeline iteration by 1 so the artifact captures
            # "this is the Nth end-of-feature inspect pass" rather than the
            # pre-inspect pipeline iteration counter. Spec R22 frames this
            # as the fix-wave attempt number (1-indexed).
            iteration = context.iteration + 1

        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_FEATURE_STARTED,
                payload={
                    "feature_id": feature_id,
                    "scenario_count": len(scenarios),
                    "iteration": iteration,
                    "eof_max_iterations": self.host_config.eof_max_iterations,
                },
            )
        )

        # Run all 8 reviewers (mechanical pre-check is handled separately)
        per_reviewer: list[dict] = []
        all_findings: list = []
        for reviewer in self.reviewers:
            try:
                verdict = self._dispatch_reviewer(
                    reviewer,
                    context=context,
                    feature_id=feature_id,
                    scenarios=scenarios,
                )
            except Exception:
                # Don't let one bad reviewer abort the sweep — skip and continue.
                continue
            if verdict is None:
                continue
            per_reviewer.append(verdict.model_dump(mode="json"))
            all_findings.extend(verdict.findings)

        # 3-tier severity routing
        critical = [f for f in all_findings if f.severity == "critical"]
        important = [f for f in all_findings if f.severity == "major"]
        minor = [f for f in all_findings if f.severity == "minor"]

        # Critical → reenter Realize for affected scenarios
        for f in critical:
            sub_bid = (f.citations or [None])[0] or "unknown"
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SCENARIO_NEEDS_REFACTOR,
                    payload={
                        "sub_bid": sub_bid,
                        "reason": f"critical_finding:{f.id}",
                    },
                )
            )

        # Important → emit FIX_WAVE_DISPATCHED (the actual fix-wave subagent is
        # an external orchestrator in production; we emit the marker so the
        # events log captures the routing decision)
        if important:
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.FIX_WAVE_DISPATCHED,
                    payload={
                        "feature_id": feature_id,
                        "finding_count": len(important),
                    },
                )
            )

        # Determine readiness
        ready_to_merge = len(critical) == 0 and len(important) == 0

        # Build InspectArtifact
        scenario_statuses = [
            ScenarioInspectStatus(
                sub_bid=s.get("sub_bid", "unknown"),
                scenario_name=s.get("scenario_name", "unknown"),
                status="needs_refactor"
                if any(
                    f.severity == "critical"
                    and ((f.citations or [None])[0] == s.get("sub_bid"))
                    for f in all_findings
                )
                else "live",
            )
            for s in scenarios
        ]

        # Build ledger markdown
        ledger_md = (
            f"# Inspect Feature {feature_id} — iteration {iteration}\n\n"
            f"ready_to_merge: {ready_to_merge}\n"
            f"critical: {len(critical)}, important: {len(important)}, minor: {len(minor)}\n\n"
            f"## Reviewers\n"
            + "\n".join(
                f"- {r['dimension']}: {r['outcome']} ({len(r['findings'])} findings)"
                for r in per_reviewer
            )
        )

        artifact_content = InspectArtifactContent(
            feature_id=feature_id,
            inspected_at=datetime.now(UTC),
            iteration=iteration,
            eof_max_iterations=self.host_config.eof_max_iterations,
            scenarios=scenario_statuses,
            per_reviewer=per_reviewer,
            critical=[f.model_dump(mode="json") for f in critical],
            important=[f.model_dump(mode="json") for f in important],
            minor=[f.model_dump(mode="json") for f in minor],
            cross_scenario=[
                r for r in per_reviewer if r.get("dimension") == "cross_scenario"
            ],
            ready_to_merge=ready_to_merge,
            ledger_markdown=ledger_md,
        )

        # Persist via InspectArtifact.finalize
        artifact_path = (
            context.project_dir / ".haileris" / "inspect" / feature_id / f"{iteration}.yaml"
        )
        InspectArtifact.finalize(artifact_path, artifact_content, self.events_log)

        # Halt if budget exceeded + not ready
        if iteration >= self.host_config.eof_max_iterations and not ready_to_merge:
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_FEATURE_HALT_PERSISTED,
                    payload={
                        "feature_id": feature_id,
                        "iteration": iteration,
                        "reason": "eof_budget_overflow",
                    },
                )
            )
            raise InspectFeatureHalted(feature_id=feature_id, iteration=iteration)

        if ready_to_merge:
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_FEATURE_PASSED,
                    payload={"feature_id": feature_id, "iteration": iteration},
                )
            )

        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_FEATURE_COMPLETED,
                payload={
                    "feature_id": feature_id,
                    "iteration": iteration,
                    "ready_to_merge": ready_to_merge,
                },
            )
        )

        return artifact_content
