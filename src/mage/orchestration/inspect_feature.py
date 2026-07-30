"""InspectFeature stage: end-of-feature verification and severity routing."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal, cast

from mage.artifacts.bid import Base85BID
from mage.artifacts.inspect import (
    CosmeticItem,
    InspectArtifact,
    InspectArtifactContent,
    InspectArtifactRef,
    ScenarioInspectStatus,
)
from mage.artifacts.verdict import ReviewerFinding, ReviewerVerdict
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.verification.host_overrides import HostConfig
from mage.verification.mechanical import (
    CheckResult,
    MechanicalFinding,
    ScenarioDraft,
)

FixWaveDispatcher = Callable[..., None]


class InspectFeatureHalted(Exception):
    """Raised when the end-of-feature iteration budget is exhausted."""

    def __init__(self, feature_id: str, iteration: int) -> None:
        self.feature_id = feature_id
        self.iteration = iteration
        super().__init__(
            f"InspectFeatureHalted for feature {feature_id!r} at iteration {iteration} "
            f"(eof_max_iterations exceeded)"
        )


def _noop_fix_wave_dispatcher(**kwargs: Any) -> None:
    """Default dispatcher used when orchestration has no external fix-wave agent."""


class InspectFeatureStage(StageNode):
    """Run the full mechanical, per-scenario, and cross-scenario feature gate."""

    name = "inspect_feature"

    def __init__(
        self,
        events_log: EventsLog,
        *,
        reviewers: list,
        mechanical_verifier,
        host_config: HostConfig,
        fix_wave_dispatcher: FixWaveDispatcher | None = None,
    ) -> None:
        super().__init__(events_log)
        self.reviewers = list(reviewers)
        self.mechanical_verifier = mechanical_verifier
        self.host_config = host_config
        self.fix_wave_dispatcher = (
            fix_wave_dispatcher or _noop_fix_wave_dispatcher
        )

    def _run(self, context: PipelineContext) -> PipelineContext:  # noqa: ARG002
        raise NotImplementedError(
            "InspectFeatureStage._run is not wired into the linear graph driver. "
            "Use run_pass with the feature id and complete scenario payloads."
        )

    @staticmethod
    def _scenario_name(scenario: dict) -> str:
        return str(scenario.get("scenario_name") or scenario.get("name") or "unknown")

    @staticmethod
    def _scenario_body(scenario: dict) -> str:
        return str(scenario.get("gherkin_body") or scenario.get("gherkin_text") or "")

    @staticmethod
    def _scenario_sub_bid(scenario: dict) -> str:
        return str(scenario.get("sub_bid") or "unknown")

    def _scenario_draft(
        self,
        context: PipelineContext,
        scenario: dict,
    ) -> ScenarioDraft:
        sub_bid = self._scenario_sub_bid(scenario)
        base_bid = str(scenario.get("base_bid") or sub_bid[:5])
        name = self._scenario_name(scenario)
        body = self._scenario_body(scenario)
        feature_path_value = scenario.get("feature_path")
        feature_path = (
            Path(feature_path_value)
            if feature_path_value is not None
            else context.project_dir / "scenarios" / base_bid / f"{name}.feature"
        )
        step_prefixes = ("Given ", "When ", "Then ", "And ", "But ")
        step_texts = [
            line.strip()
            for line in body.splitlines()
            if line.strip().startswith(step_prefixes)
        ]
        return ScenarioDraft(
            feature_path=feature_path,
            scenario_name=name,
            gherkin_text=body,
            tags=list(scenario.get("tags") or []),
            sub_bid=sub_bid,
            parent_base_bid=Base85BID(value=base_bid),
            step_texts=step_texts,
        )

    @staticmethod
    def _mechanical_finding(
        item: Any,
        *,
        sub_bid: str,
        scenario_name: str,
    ) -> ReviewerFinding | None:
        severity: Literal["critical", "major", "minor"]
        if isinstance(item, CheckResult):
            if item.outcome == "pass":
                return None
            check = item.name
            severity = "critical"
            detail = item.detail or f"{item.name} failed"
            location = f"{scenario_name} ({sub_bid})"
        elif isinstance(item, MechanicalFinding):
            check = item.check
            severity = item.severity
            detail = item.issue
            location = item.location or f"{scenario_name} ({sub_bid})"
        else:
            outcome = getattr(item, "outcome", None)
            if outcome == "pass":
                return None
            check = str(getattr(item, "check", getattr(item, "name", "unknown")))
            raw_severity = getattr(item, "severity", "critical")
            severity = cast(
                Literal["critical", "major", "minor"],
                raw_severity
                if raw_severity in {"critical", "major", "minor"}
                else "critical",
            )
            detail = str(
                getattr(item, "issue", None)
                or getattr(item, "detail", None)
                or f"{check} failed"
            )
            location = str(
                getattr(item, "location", None) or f"{scenario_name} ({sub_bid})"
            )
        return ReviewerFinding(
            id=f"mechanical:{check}:{sub_bid}",
            severity=severity,
            location=location,
            issue=detail,
            rationale=detail,
            suggestion="Correct the mechanical verification failure before review.",
            citations=[sub_bid],
        )

    def _run_mechanical_precheck(
        self,
        context: PipelineContext,
        scenarios: list[dict],
    ) -> tuple[list[dict], list[tuple[ReviewerFinding, str, dict | None]]]:
        records: list[dict] = []
        findings_with_source: list[tuple[ReviewerFinding, str, dict | None]] = []
        for scenario in scenarios:
            draft = self._scenario_draft(context, scenario)
            results = self.mechanical_verifier.verify(draft, context.mapping)
            findings = [
                finding
                for item in results
                if (
                    finding := self._mechanical_finding(
                        item,
                        sub_bid=draft.sub_bid,
                        scenario_name=draft.scenario_name,
                    )
                )
                is not None
            ]
            records.append(
                {
                    "dimension": "mechanical",
                    "outcome": "fail" if findings else "pass",
                    "draft_hash": "",
                    "reviewed_at": datetime.now(UTC).isoformat(),
                    "reviewer_id": "mechanical@v1",
                    "scenario_sub_bid": draft.sub_bid,
                    "findings": [
                        finding.model_dump(mode="json") for finding in findings
                    ],
                    "checks": [
                        item.model_dump(mode="json")
                        if hasattr(item, "model_dump")
                        else {"name": str(item)}
                        for item in results
                    ],
                }
            )
            findings_with_source.extend(
                (finding, "mechanical", scenario) for finding in findings
            )
            self.events_log.append_sync(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=(
                        EventType.MECHANICAL_PRECHECK_FAILED
                        if findings
                        else EventType.MECHANICAL_PRECHECK_PASSED
                    ),
                    payload={
                        "scope": "feature",
                        "sub_bid": draft.sub_bid,
                        "finding_count": len(findings),
                    },
                )
            )
        return records, findings_with_source

    def _dispatch_scenario_reviewer(
        self,
        reviewer,
        *,
        context: PipelineContext,
        feature_id: str,
        scenario: dict,
    ) -> ReviewerVerdict:
        from mage.agents.inscribe import ScenarioSpec

        sub_bid = self._scenario_sub_bid(scenario)
        draft = ScenarioSpec(
            name=self._scenario_name(scenario),
            gherkin_body=self._scenario_body(scenario),
            tags=list(scenario.get("tags") or []),
            notes=str(scenario.get("notes") or ""),
            cross_behavior_tags=list(scenario.get("cross_behavior_tags") or []),
        )
        spec_context = {
            "feature_id": feature_id,
            "scenario_name": draft.name,
            "sub_bid": sub_bid,
            "base_bid": scenario.get("base_bid") or sub_bid[:5],
        }
        verdict_path = (
            context.project_dir
            / ".haileris"
            / "verdicts"
            / feature_id
            / sub_bid
            / f"{reviewer.dimension}.yaml"
        )
        verdict = reviewer.run(
            draft=draft,
            spec_context=spec_context,
            mapping=context.mapping,
            events_log=self.events_log,
            verdict_path=verdict_path,
        )
        if not isinstance(verdict, ReviewerVerdict):
            raise TypeError(
                f"reviewer {reviewer.dimension!r} returned "
                f"{type(verdict).__name__}, expected ReviewerVerdict"
            )
        return verdict

    def _run_reviewers(
        self,
        context: PipelineContext,
        *,
        feature_id: str,
        scenarios: list[dict],
    ) -> tuple[list[dict], list[tuple[ReviewerFinding, str, dict | None]]]:
        records: list[dict] = []
        findings_with_source: list[tuple[ReviewerFinding, str, dict | None]] = []
        scenario_reviewers = [
            reviewer
            for reviewer in self.reviewers
            if getattr(reviewer, "dimension", "") != "cross_scenario"
        ]
        cross_reviewers = [
            reviewer
            for reviewer in self.reviewers
            if getattr(reviewer, "dimension", "") == "cross_scenario"
        ]

        for scenario in scenarios:
            for reviewer in scenario_reviewers:
                verdict = self._dispatch_scenario_reviewer(
                    reviewer,
                    context=context,
                    feature_id=feature_id,
                    scenario=scenario,
                )
                record = verdict.model_dump(mode="json")
                record["scenario_sub_bid"] = self._scenario_sub_bid(scenario)
                records.append(record)
                findings_with_source.extend(
                    (finding, verdict.dimension, scenario)
                    for finding in verdict.findings
                )

        for reviewer in cross_reviewers:
            verdict = reviewer.run(
                feature_summary={"feature_id": feature_id},
                scenarios=scenarios,
                mapping=context.mapping,
            )
            if not isinstance(verdict, ReviewerVerdict):
                raise TypeError(
                    f"reviewer {reviewer.dimension!r} returned "
                    f"{type(verdict).__name__}, expected ReviewerVerdict"
                )
            records.append(verdict.model_dump(mode="json"))
            findings_with_source.extend(
                (finding, verdict.dimension, None) for finding in verdict.findings
            )
        return records, findings_with_source

    @staticmethod
    def _affected_sub_bids(
        finding: ReviewerFinding,
        scenarios: list[dict],
    ) -> list[str]:
        known = {
            str(scenario.get("sub_bid"))
            for scenario in scenarios
            if scenario.get("sub_bid") is not None
        }
        cited = [citation for citation in finding.citations if citation in known]
        return cited or sorted(known)

    def _append_cosmetics(
        self,
        context: PipelineContext,
        findings: list[tuple[ReviewerFinding, str, dict | None]],
        scenarios: list[dict],
    ) -> None:
        by_sub_bid = {
            self._scenario_sub_bid(scenario): scenario for scenario in scenarios
        }
        for finding, dimension, source_scenario in findings:
            cited_sub_bid = finding.citations[0] if finding.citations else None
            scenario = source_scenario or by_sub_bid.get(str(cited_sub_bid))
            sub_bid = (
                self._scenario_sub_bid(scenario)
                if scenario is not None
                else str(cited_sub_bid or "unknown")
            )
            scenario_name = (
                self._scenario_name(scenario)
                if scenario is not None
                else "unknown"
            )
            context.mapping = context.mapping.append_cosmetic(
                CosmeticItem(
                    sub_bid=sub_bid,
                    scenario_name=scenario_name,
                    location=finding.location,
                    text=finding.suggestion or finding.issue,
                    proposed_by=dimension,
                )
            )

    @staticmethod
    def _fix_wave_brief(feature_id: str, findings: list[dict]) -> str:
        lines = [f"# Fix wave for {feature_id}", ""]
        for finding in findings:
            lines.extend(
                [
                    f"- [{finding['id']}] {finding['issue']}",
                    f"  - location: {finding['location']}",
                    f"  - rationale: {finding['rationale']}",
                    f"  - suggested fix: {finding.get('suggestion') or '(none)'}",
                ]
            )
        return "\n".join(lines) + "\n"

    def _run_iteration(
        self,
        context: PipelineContext,
        *,
        feature_id: str,
        scenarios: list[dict],
        iteration: int,
    ) -> InspectArtifactContent:
        self.events_log.append_sync(
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

        per_reviewer, sourced_findings = self._run_mechanical_precheck(
            context, scenarios
        )
        if not sourced_findings:
            reviewer_records, reviewer_findings = self._run_reviewers(
                context,
                feature_id=feature_id,
                scenarios=scenarios,
            )
            per_reviewer.extend(reviewer_records)
            sourced_findings.extend(reviewer_findings)

        critical = [
            item for item in sourced_findings if item[0].severity == "critical"
        ]
        important = [
            item for item in sourced_findings if item[0].severity == "major"
        ]
        minor = [
            item for item in sourced_findings if item[0].severity == "minor"
        ]

        for finding, _dimension, _scenario in critical:
            for sub_bid in self._affected_sub_bids(finding, scenarios):
                self.events_log.append_sync(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.SCENARIO_NEEDS_REFACTOR,
                        payload={
                            "sub_bid": sub_bid,
                            "reason": f"critical_finding:{finding.id}",
                        },
                    )
                )

        ready_to_merge = not critical and not important
        critical_sub_bids = {
            sub_bid
            for finding, _dimension, _scenario in critical
            for sub_bid in self._affected_sub_bids(finding, scenarios)
        }
        scenario_statuses = [
            ScenarioInspectStatus(
                sub_bid=self._scenario_sub_bid(scenario),
                scenario_name=self._scenario_name(scenario),
                status=(
                    "needs_refactor"
                    if self._scenario_sub_bid(scenario) in critical_sub_bids
                    else "live"
                ),
            )
            for scenario in scenarios
        ]
        critical_models = [
            finding.model_dump(mode="json")
            for finding, _dimension, _scenario in critical
        ]
        important_models = [
            finding.model_dump(mode="json")
            for finding, _dimension, _scenario in important
        ]
        minor_models = [
            finding.model_dump(mode="json")
            for finding, _dimension, _scenario in minor
        ]
        cross_scenario_models = [
            finding.model_dump(mode="json")
            for finding, dimension, _scenario in sourced_findings
            if dimension == "cross_scenario"
        ]
        ledger = (
            f"# Inspect Feature {feature_id} — iteration {iteration}\n\n"
            f"ready_to_merge: {ready_to_merge}\n"
            f"critical: {len(critical)}, important: {len(important)}, "
            f"minor: {len(minor)}\n\n"
            "## Reviewers\n"
            + "\n".join(
                f"- {record['dimension']}: {record['outcome']} "
                f"({len(record['findings'])} findings)"
                for record in per_reviewer
            )
        )
        inspected_at = datetime.now(UTC)
        content = InspectArtifactContent(
            feature_id=feature_id,
            inspected_at=inspected_at,
            iteration=iteration,
            eof_max_iterations=self.host_config.eof_max_iterations,
            scenarios=scenario_statuses,
            per_reviewer=per_reviewer,
            critical=critical_models,
            important=important_models,
            minor=minor_models,
            cross_scenario=cross_scenario_models,
            ready_to_merge=ready_to_merge,
            ledger_markdown=ledger,
        )
        artifact_path = (
            context.project_dir
            / ".haileris"
            / "inspect"
            / feature_id
            / f"{iteration}.yaml"
        )
        digest = InspectArtifact.finalize(
            artifact_path,
            content,
            self.events_log,
        )
        context.mapping = context.mapping.attach_feature_inspect(
            InspectArtifactRef(
                inspect_path=str(artifact_path),
                inspect_sha256=digest,
                finalized_at=datetime.now(UTC),
            )
        )
        self._append_cosmetics(context, minor, scenarios)
        context.mapping = context.mapping.model_copy(
            update={
                "feature_status": (
                    "inspect_passed" if ready_to_merge else "inspect_pending"
                )
            }
        )
        context.mapping.save(context.project_dir / "mapping.yaml")

        if iteration >= self.host_config.eof_max_iterations and not ready_to_merge:
            context.mapping = context.mapping.model_copy(
                update={"feature_status": "halted"}
            )
            context.mapping.save(context.project_dir / "mapping.yaml")
            self.events_log.append_sync(
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
            self.events_log.append_sync(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.INSPECT_FEATURE_PASSED,
                    payload={"feature_id": feature_id, "iteration": iteration},
                )
            )

        self.events_log.append_sync(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSPECT_FEATURE_COMPLETED,
                payload={
                    "feature_id": feature_id,
                    "iteration": iteration,
                    "ready_to_merge": ready_to_merge,
                    "scenario_statuses": [
                        status.model_dump(mode="json")
                        for status in scenario_statuses
                    ],
                },
            )
        )
        return content

    def run_pass(
        self,
        context: PipelineContext,
        *,
        feature_id: str,
        scenarios: list[dict],
        iteration: int | None = None,
    ) -> InspectArtifactContent:
        """Run Inspect, dispatching Important fix waves until clean or exhausted."""
        current_iteration = iteration or (context.iteration + 1)
        while True:
            context.iteration = current_iteration
            content = self._run_iteration(
                context,
                feature_id=feature_id,
                scenarios=scenarios,
                iteration=current_iteration,
            )
            if content.ready_to_merge or content.critical:
                return content

            brief = self._fix_wave_brief(feature_id, content.important)
            self.fix_wave_dispatcher(
                context=context,
                feature_id=feature_id,
                iteration=current_iteration,
                brief=brief,
                findings=content.important,
            )
            self.events_log.append_sync(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.FIX_WAVE_DISPATCHED,
                    payload={
                        "feature_id": feature_id,
                        "iteration": current_iteration,
                        "finding_count": len(content.important),
                        "brief": brief,
                    },
                )
            )
            current_iteration += 1
