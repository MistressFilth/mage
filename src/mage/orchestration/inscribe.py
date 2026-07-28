"""Inscribe stage: orchestrates per-behavior scenario drafting + approval gate."""

from __future__ import annotations

import hashlib
from datetime import datetime, UTC
from pathlib import Path

import yaml

from mage.agents.inscribe import InscribeAgent
from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import (
    LifecycleStatus,
    MappingArtifact,
    ScenarioEntry,
)
from mage.artifacts.verdict import VerdictArtifact
from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.verification.host_overrides import HostConfig
from mage.verification.mechanical import MechanicalVerifier, ScenarioDraft
from mage.verification.reviewers.base import ReviewerAgent, compute_draft_hash
from mage.verification.reviewers.registry import aggregate_verdicts


class ReviewBudgetExhausted(Exception):
    """Raised when the iteration budget is exhausted without reaching approved."""

    def __init__(self, base_bid: str, scenario_name: str, iteration: int) -> None:
        self.base_bid = base_bid
        self.scenario_name = scenario_name
        self.iteration = iteration
        super().__init__(
            f"Review budget exhausted for scenario {scenario_name!r} "
            f"under base_bid {base_bid!r} at iteration {iteration}"
        )


class InscribeStage(StageNode):
    """Runs once per feature; loops over behaviors and scenarios to APPROVED."""

    name = "inscribe"

    def __init__(
        self,
        events_log: EventsLog,
        agent: InscribeAgent,
        host_config: HostConfig,
        reviewers: list[ReviewerAgent],
        mechanical_verifier: MechanicalVerifier | None = None,
    ) -> None:
        super().__init__(events_log)
        self.agent = agent
        self.host_config = host_config
        self.reviewers = reviewers
        self.mechanical_verifier = mechanical_verifier or MechanicalVerifier(checks=[])

    def _run(self, context: PipelineContext) -> PipelineContext:
        project_dir: Path = context.project_dir

        # Emit INSCRIBE_STARTED
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSCRIBE_STARTED,
                payload={
                    "feature_id": "unknown",  # Plan 3 spec: emit but don't enforce
                    "reviewer_count": len(self.reviewers),
                    "iteration": context.iteration,
                },
            )
        )

        # Load behaviors.yaml
        behaviors_data = yaml.safe_load((project_dir / "behaviors.yaml").read_text())
        behavior_specs = behaviors_data["behaviors"]

        # I3: use the in-memory mapping (source of truth) rather than re-reading
        # the on-disk artifact; any changes from prior stages are reflected here.
        mapping = context.mapping

        # Iterate behaviors (in plan order — topological; Plan 3 just uses source order)
        iteration = context.iteration
        for beh in behavior_specs:
            base_bid = beh["id"]
            behavior_name = beh["name"]
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.BEHAVIOR_INSCRIBE_STARTED,
                    payload={"base_bid": base_bid, "behavior_name": behavior_name},
                )
            )

            # Find the BaseBIDEntry
            entry = next(e for e in mapping.base_bids if e.base_bid == base_bid)
            # I2: existing_scenarios currently uses sub_bid as a placeholder name
            # and an empty body. ScenarioEntry doesn't carry scenario_name or
            # gherkin_body, so we can't reconstruct the real on-disk scenario
            # text without a separate file lookup. Defer the proper lookup to
            # Plan 6, which adds a richer scenario metadata entry; for now
            # the agent sees the sub_bid so it doesn't draft duplicates of
            # the same scenario (the InscribeAgent already keys on sub_bid).
            # TODO(plan6): replace sub_bid placeholder with real name+gherkin.
            existing_scenarios = [
                {"name": s.sub_bid, "gherkin_body": ""} for s in entry.scenarios
            ]

            # Inscribe loop (one behavior → may produce 1+ scenarios, but for Plan 3
            # the test focuses on a single scenario per behavior).
            approved = False
            while iteration < self.host_config.max_iterations and not approved:
                iteration += 1
                # Draft scenarios
                output = self.agent.run(
                    behavior=entry, existing_scenarios=existing_scenarios, mapping=mapping
                )

                # For each scenario, run mechanical pre-check, then 7 reviewers + aggregate
                approved = True  # assume all approved; revise if any fail
                for scenario_idx, scenario in enumerate(output.scenarios):
                    self.events_log.append(
                        Event(
                            timestamp=datetime.now(UTC),
                            event_type=EventType.SCENARIO_DRAFTED,
                            payload={
                                "base_bid": base_bid,
                                "scenario_name": scenario.name,
                                "iteration": iteration,
                            },
                        )
                    )

                    # C1: mechanical pre-check BEFORE the reviewer loop.
                    # Build a ScenarioDraft from the freshly drafted scenario.
                    # Use a synthetic sub_bid="-" because the real sub_bid is
                    # only assigned when the scenario is approved; the
                    # SubBidAssignedCheck still validates Base85 alphabet,
                    # but the pre-check is best-effort at draft time.
                    draft_for_precheck = ScenarioDraft(
                        feature_path=project_dir / "scenarios" / base_bid / f"{scenario.name}.feature",
                        scenario_name=scenario.name,
                        gherkin_text=scenario.gherkin_body,
                        tags=list(scenario.tags),
                        sub_bid="-",
                        parent_base_bid=Base85BID(value=base_bid),
                        step_texts=[],
                    )
                    precheck_results = self.mechanical_verifier.verify(
                        draft_for_precheck, mapping
                    )
                    precheck_passed = self.mechanical_verifier.all_passed(precheck_results)
                    if precheck_passed:
                        self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.MECHANICAL_PRECHECK_PASSED,
                                payload={
                                    "base_bid": base_bid,
                                    "scenario_name": scenario.name,
                                    "iteration": iteration,
                                    "checks_run": len(precheck_results),
                                },
                            )
                        )
                    else:
                        failed = [r for r in precheck_results if r.outcome == "fail"]
                        self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.MECHANICAL_PRECHECK_FAILED,
                                payload={
                                    "base_bid": base_bid,
                                    "scenario_name": scenario.name,
                                    "iteration": iteration,
                                    "failed_checks": [r.name for r in failed],
                                    "details": {r.name: r.detail for r in failed},
                                },
                            )
                        )
                        # Pre-check failure → treat as needs_refactor.
                        approved = False
                        self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.SCENARIO_NEEDS_REFACTOR,
                                payload={
                                    "base_bid": base_bid,
                                    "scenario_name": scenario.name,
                                    "reason": "mechanical_precheck_failed",
                                },
                            )
                        )
                        # Skip the reviewer loop for this scenario; go to next iteration.
                        break

                    # Compute draft_hash for per-draft verdict storage namespace.
                    spec_context = {"behavior_name": behavior_name}
                    draft_hash = compute_draft_hash(scenario, spec_context)

                    # C3: verdicts keyed by draft_hash (not iteration) so the
                    # aggregate's reviewer_verdict_ref paths resolve.
                    verdicts_dir = project_dir / ".haileris" / "verdicts" / draft_hash
                    verdicts_dir.mkdir(parents=True, exist_ok=True)

                    # C2: honor HostConfig.enabled_reviewers (the host-project
                    # override mechanism). When None, run all reviewers.
                    enabled_set = (
                        set(self.host_config.enabled_reviewers)
                        if self.host_config.enabled_reviewers is not None
                        else None
                    )
                    reviewers_to_run = (
                        [r for r in self.reviewers if r.dimension in enabled_set]
                        if enabled_set is not None
                        else list(self.reviewers)
                    )

                    # Run each enabled reviewer; verdicts stored alongside aggregate.
                    per_dimension_verdicts = {}
                    for reviewer in reviewers_to_run:
                        verdict_path = verdicts_dir / f"{reviewer.dimension}.yaml"
                        verdict = reviewer.run(
                            draft=scenario,
                            spec_context=spec_context,
                            mapping=mapping,
                            events_log=self.events_log,
                            verdict_path=verdict_path,
                        )
                        per_dimension_verdicts[reviewer.dimension] = verdict

                    # Aggregate (registry builds reviewer_verdict_ref as
                    # `.haileris/verdicts/{draft_hash}/{dimension}.yaml`).
                    aggregate = aggregate_verdicts(per_dimension_verdicts, iteration=iteration)
                    aggregate_path = verdicts_dir / "aggregate.yaml"
                    # C4: VerdictArtifact.finalize already emits REVIEW_AGGREGATE_RECORDED;
                    # do NOT manually re-emit it here.
                    VerdictArtifact.finalize(aggregate_path, aggregate, self.events_log)

                    if aggregate.decision == "approved":
                        # Assign sub-BID
                        parent_bid = Base85BID(value=base_bid)
                        sub_bid = Base85BID.derive(parent_bid, scenario_idx)
                        scenario_text_hash = hashlib.sha256(
                            scenario.gherkin_body.encode("utf-8")
                        ).hexdigest()

                        scenario_entry = ScenarioEntry(
                            sub_bid=sub_bid.value,
                            scenario_text_hash=scenario_text_hash,
                            lifecycle_status=LifecycleStatus.APPROVED,
                        )
                        mapping = mapping.append_scenario(base_bid, scenario_entry)
                        # Write scenario file
                        scenario_dir = project_dir / "scenarios" / base_bid
                        scenario_dir.mkdir(parents=True, exist_ok=True)
                        scenario_path = scenario_dir / f"{scenario.name}.feature"
                        scenario_path.write_text(scenario.gherkin_body, encoding="utf-8")

                        self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.SCENARIO_APPROVED,
                                payload={
                                    "base_bid": base_bid,
                                    "sub_bid": sub_bid.value,
                                    "scenario_text_hash": scenario_text_hash,
                                },
                            )
                        )
                    else:
                        # needs_refactor: loop
                        approved = False
                        self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.SCENARIO_NEEDS_REFACTOR,
                                payload={"base_bid": base_bid, "scenario_name": scenario.name},
                            )
                        )

            if not approved:
                # Budget exhausted: emit halt event and raise.
                self.events_log.append(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.REVIEW_HALT_PERSISTED,
                        payload={
                            "base_bid": base_bid,
                            "behavior_name": behavior_name,
                            "iteration": iteration,
                            "max_iterations": self.host_config.max_iterations,
                        },
                    )
                )
                # I5: pass behavior_name as the exception's scenario_name for
                # now; scenario-level granularity (each scenario exhausted
                # independently) is Plan 6 territory.
                # TODO(plan6): emit halt per-scenario rather than per-behavior.
                raise ReviewBudgetExhausted(
                    base_bid=base_bid,
                    scenario_name=behavior_name,
                    iteration=iteration,
                )

            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.BEHAVIOR_INSCRIBE_COMPLETED,
                    payload={"base_bid": base_bid, "iteration": iteration},
                )
            )

        # Persist updated mapping
        mapping.save(project_dir / "mapping.yaml")

        # Emit INSCRIBE_COMPLETED
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSCRIBE_COMPLETED,
                payload={
                    "feature_id": "unknown",
                    "scenario_count": sum(
                        len(e.scenarios) for e in mapping.base_bids
                    ),
                    "iteration": iteration,
                },
            )
        )

        return context.model_copy(update={"mapping": mapping, "iteration": iteration})