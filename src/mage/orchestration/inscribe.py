"""Inscribe stage: orchestrates per-behavior scenario drafting + approval gate."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import yaml

from mage.agents.inscribe import InscribeAgent
from mage.artifacts.bid import Base85BID
from mage.artifacts.mapping import (
    LifecycleStatus,
    ScenarioEntry,
)
from mage.artifacts.verdict import VerdictArtifact
from mage.orchestration.discipline.policy import acquire_cycle_lock, release_cycle_lock
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.verification.host_overrides import HostConfig
from mage.verification.mechanical import MechanicalVerifier, ScenarioDraft
from mage.verification.reviewers.base import ReviewerAgent, compute_draft_hash
from mage.verification.reviewers.registry import aggregate_verdicts


class ReviewBudgetExhausted(Exception):
    """Raised when the iteration budget is exhausted without reaching approved.

    Plan 25: halted_sub_bids is the list of sub_bids whose per-scenario
    iteration budget ran out. The behavior-level halt is the union of
    per-scenario halts in the same behavior.
    """

    def __init__(
        self,
        base_bid: str,
        scenario_name: str,
        iteration: int,
        halted_sub_bids: list[str],
    ) -> None:
        self.base_bid = base_bid
        self.scenario_name = scenario_name
        self.iteration = iteration
        self.halted_sub_bids = halted_sub_bids
        super().__init__(
            f"Review budget exhausted for behavior {scenario_name!r} "
            f"under base_bid {base_bid!r} at iteration {iteration} "
            f"(halted_sub_bids={halted_sub_bids})"
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

    async def _run(self, context: PipelineContext) -> PipelineContext:
        project_dir: Path = context.project_dir

        # Emit INSCRIBE_STARTED
        await self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSCRIBE_STARTED,
                payload={
                    "feature_id": context.feature_id,
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
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.BEHAVIOR_INSCRIBE_STARTED,
                    payload={"base_bid": base_bid, "behavior_name": behavior_name},
                )
            )

            # Find the BaseBIDEntry
            entry = next(e for e in mapping.base_bids if e.base_bid == base_bid)

            # I2 fix (Plan 25): existing_scenarios uses real scenario_name +
            # gherkin_body from the prior Scenarios on the BaseBIDEntry. Pre-
            # migration entries default to empty strings — the agent sees
            # "" until the next draft pass populates them.
            existing_scenarios = [
                {"name": s.scenario_name, "gherkin_body": s.gherkin_body}
                for s in entry.scenarios
            ]

            # Plan 25: per-scenario iteration tracking. Each scenario gets
            # its own iteration counter; halts are per-scenario, not per-
            # behavior. Sibling scenarios in the same behavior continue
            # drafting when one of them exhausts its budget.
            prior_subs = {s.sub_bid for s in entry.scenarios}
            per_scenario_iter: dict[str, int] = {
                s.sub_bid: iteration for s in entry.scenarios
            }
            halted_scenarios: set[str] = set()

            approved = False
            while not approved:
                # Draft scenarios from the agent.
                output = await self.agent.run(
                    behavior=entry,
                    existing_scenarios=existing_scenarios,
                    mapping=mapping,
                )

                # For each scenario in this draft, run the mechanical pre-
                # check then the reviewer loop. Each scenario gets its own
                # iteration counter.
                any_failed = False
                for scenario_idx, scenario in enumerate(output.scenarios):
                    # Plan 25: derive the sub_bid up front so iteration
                    # tracking and halt events can carry it.
                    parent_bid = Base85BID(value=base_bid)
                    sub_bid = Base85BID.derive(parent_bid, scenario_idx).value
                    per_scenario_iter.setdefault(sub_bid, iteration)

                    # Check halt first.
                    if per_scenario_iter[sub_bid] >= self.host_config.max_iterations:
                        await self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.SCENARIO_HALT_PERSISTED,
                                payload={
                                    "base_bid": base_bid,
                                    "behavior_name": behavior_name,
                                    "sub_bid": sub_bid,
                                    "scenario_name": scenario.name,
                                    "iteration": per_scenario_iter[sub_bid],
                                    "max_iterations": self.host_config.max_iterations,
                                },
                            )
                        )
                        halted_scenarios.add(sub_bid)
                        continue

                    # Emit SCENARIO_DRAFTED.
                    await self.events_log.append(
                        Event(
                            timestamp=datetime.now(UTC),
                            event_type=EventType.SCENARIO_DRAFTED,
                            payload={
                                "base_bid": base_bid,
                                "scenario_name": scenario.name,
                                "iteration": per_scenario_iter[sub_bid],
                            },
                        )
                    )

                    # Mechanical pre-check (unchanged contract).
                    draft_for_precheck = ScenarioDraft(
                        feature_path=project_dir
                        / "scenarios"
                        / base_bid
                        / f"{scenario.name}.feature",
                        scenario_name=scenario.name,
                        gherkin_text=scenario.gherkin_body,
                        tags=list(scenario.tags),
                        sub_bid=sub_bid,
                        parent_base_bid=parent_bid,
                        step_texts=[],
                    )
                    precheck_results = self.mechanical_verifier.verify(
                        draft_for_precheck, mapping
                    )
                    precheck_passed = self.mechanical_verifier.all_passed(
                        precheck_results
                    )
                    if precheck_passed:
                        await self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.MECHANICAL_PRECHECK_PASSED,
                                payload={
                                    "base_bid": base_bid,
                                    "scenario_name": scenario.name,
                                    "iteration": per_scenario_iter[sub_bid],
                                    "checks_run": len(precheck_results),
                                },
                            )
                        )
                    else:
                        failed = [r for r in precheck_results if r.outcome == "fail"]
                        await self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.MECHANICAL_PRECHECK_FAILED,
                                payload={
                                    "base_bid": base_bid,
                                    "scenario_name": scenario.name,
                                    "iteration": per_scenario_iter[sub_bid],
                                    "failed_checks": [r.name for r in failed],
                                    "details": {r.name: r.detail for r in failed},
                                },
                            )
                        )
                        # Treat as needs_refactor: halt this scenario.
                        await self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.SCENARIO_HALT_PERSISTED,
                                payload={
                                    "base_bid": base_bid,
                                    "behavior_name": behavior_name,
                                    "sub_bid": sub_bid,
                                    "scenario_name": scenario.name,
                                    "iteration": per_scenario_iter[sub_bid],
                                    "max_iterations": self.host_config.max_iterations,
                                    "reason": "mechanical_precheck_failed",
                                },
                            )
                        )
                        halted_scenarios.add(sub_bid)
                        any_failed = True
                        continue

                    # Reviewer loop (unchanged contract).
                    spec_context = {"behavior_name": behavior_name}
                    draft_hash = compute_draft_hash(scenario, spec_context)
                    verdicts_dir = project_dir / ".mage" / "verdicts" / draft_hash
                    verdicts_dir.mkdir(parents=True, exist_ok=True)

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

                    semaphore = asyncio.Semaphore(
                        self.host_config.max_concurrent_llm_calls
                    )

                    async def run_one(
                        reviewer,
                        *,
                        _semaphore=semaphore,
                        _verdicts_dir=verdicts_dir,
                        _scenario=scenario,
                        _spec_context=spec_context,
                        _mapping=mapping,
                    ):
                        async with _semaphore:
                            verdict_path = _verdicts_dir / f"{reviewer.dimension}.yaml"
                            return (
                                reviewer.dimension,
                                await reviewer.run(
                                    draft=_scenario,
                                    spec_context=_spec_context,
                                    mapping=_mapping,
                                    events_log=self.events_log,
                                    verdict_path=verdict_path,
                                ),
                            )

                    results = await asyncio.gather(
                        *[run_one(r) for r in reviewers_to_run]
                    )
                    per_dimension_verdicts = dict(results)
                    aggregate = aggregate_verdicts(
                        per_dimension_verdicts,
                        iteration=per_scenario_iter[sub_bid],
                    )
                    aggregate_path = verdicts_dir / "aggregate.yaml"
                    await VerdictArtifact.finalize(
                        aggregate_path, aggregate, self.events_log
                    )

                    if aggregate.decision == "approved":
                        await acquire_cycle_lock(context, sub_bid)
                        scenario_text_hash = hashlib.sha256(
                            scenario.gherkin_body.encode("utf-8")
                        ).hexdigest()
                        scenario_entry = ScenarioEntry(
                            sub_bid=sub_bid,
                            scenario_name=scenario.name,
                            gherkin_body=scenario.gherkin_body,
                            scenario_text_hash=scenario_text_hash,
                            lifecycle_status=LifecycleStatus.APPROVED,
                            feature_id=context.feature_id,
                        )
                        mapping = mapping.append_scenario(base_bid, scenario_entry)
                        scenario_dir = project_dir / "scenarios" / base_bid
                        scenario_dir.mkdir(parents=True, exist_ok=True)
                        scenario_path = scenario_dir / f"{scenario.name}.feature"
                        scenario_path.write_text(
                            scenario.gherkin_body, encoding="utf-8"
                        )
                        await release_cycle_lock(context)
                        await self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.SCENARIO_APPROVED,
                                payload={
                                    "base_bid": base_bid,
                                    "sub_bid": sub_bid,
                                    "scenario_text_hash": scenario_text_hash,
                                },
                            )
                        )
                    else:
                        # needs_refactor: halt this scenario, emit halt event.
                        await self.events_log.append(
                            Event(
                                timestamp=datetime.now(UTC),
                                event_type=EventType.SCENARIO_HALT_PERSISTED,
                                payload={
                                    "base_bid": base_bid,
                                    "behavior_name": behavior_name,
                                    "sub_bid": sub_bid,
                                    "scenario_name": scenario.name,
                                    "iteration": per_scenario_iter[sub_bid],
                                    "max_iterations": self.host_config.max_iterations,
                                    "reason": "aggregate_needs_refactor",
                                },
                            )
                        )
                        halted_scenarios.add(sub_bid)
                        any_failed = True

                    # Increment per-scenario iteration regardless of outcome.
                    per_scenario_iter[sub_bid] += 1

                # Continue looping if any scenario failed; the next draft
                # will surface the same set of scenarios for refactor.
                approved = not any_failed

            # After all scenarios settled: emit REVIEW_HALT_PERSISTED if any
            # halted, then raise ReviewBudgetExhausted once per behavior.
            if halted_scenarios:
                new_halt = sorted(halted_scenarios - prior_subs)
                await self.events_log.append(
                    Event(
                        timestamp=datetime.now(UTC),
                        event_type=EventType.REVIEW_HALT_PERSISTED,
                        payload={
                            "base_bid": base_bid,
                            "behavior_name": behavior_name,
                            "halted_sub_bids": sorted(halted_scenarios),
                            "iteration": max(per_scenario_iter.values()),
                            "max_iterations": self.host_config.max_iterations,
                        },
                    )
                )
                if new_halt:
                    raise ReviewBudgetExhausted(
                        base_bid=base_bid,
                        scenario_name=behavior_name,
                        iteration=max(per_scenario_iter.values()),
                        halted_sub_bids=sorted(halted_scenarios),
                    )

            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.BEHAVIOR_INSCRIBE_COMPLETED,
                    payload={"base_bid": base_bid, "iteration": iteration},
                )
            )

        # Persist updated mapping
        await mapping.save(project_dir / "mapping.yaml")

        # Emit INSCRIBE_COMPLETED
        await self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.INSCRIBE_COMPLETED,
                payload={
                    "feature_id": context.feature_id,
                    "scenario_count": sum(len(e.scenarios) for e in mapping.base_bids),
                    "iteration": iteration,
                },
            )
        )

        return context.model_copy(update={"mapping": mapping, "iteration": iteration})
