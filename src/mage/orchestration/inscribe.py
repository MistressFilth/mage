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
from mage.verification.mechanical import MechanicalVerifier
from mage.verification.reviewers.base import ReviewerAgent
from mage.verification.reviewers.registry import aggregate_verdicts


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

        # Load mapping
        mapping = MappingArtifact.load(project_dir / "mapping.yaml")

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

                # For each scenario, run 7 reviewers + aggregate
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

                    # 7 reviewers
                    per_dimension_verdicts = {}
                    verdicts_dir = project_dir / ".haileris" / "verdicts" / f"iter-{iteration}"
                    verdicts_dir.mkdir(parents=True, exist_ok=True)
                    for reviewer in self.reviewers:
                        verdict_path = verdicts_dir / f"{reviewer.dimension}.yaml"
                        verdict = reviewer.run(
                            draft=scenario,
                            spec_context={"behavior_name": behavior_name},
                            mapping=mapping,
                            events_log=self.events_log,
                            verdict_path=verdict_path,
                        )
                        per_dimension_verdicts[reviewer.dimension] = verdict

                    # Aggregate
                    aggregate = aggregate_verdicts(per_dimension_verdicts, iteration=iteration)
                    aggregate_path = verdicts_dir / "aggregate.yaml"
                    VerdictArtifact.finalize(aggregate_path, aggregate, self.events_log)
                    self.events_log.append(
                        Event(
                            timestamp=datetime.now(UTC),
                            event_type=EventType.REVIEW_AGGREGATE_RECORDED,
                            payload={
                                "draft_hash": aggregate.draft_hash,
                                "decision": aggregate.decision,
                            },
                        )
                    )

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
