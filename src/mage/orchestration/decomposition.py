"""Decomposition stage: orchestrates agent run, behavior enumeration, plan writing, finalization."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from mage.agents.decomposition import DecompositionAgent
from mage.artifacts.ascertain import parse_ascertain
from mage.artifacts.enumeration import enumerate_behaviors
from mage.artifacts.plan import PlanArtifact
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.nodes import PipelineContext, StageNode
from mage.orchestration.plan_writer import render_plan
from mage.verification.host_overrides import HostConfig

DEFAULT_TEMPLATE_PATH = Path(__file__).parent / "plan_template.md"


class DecompositionStage(StageNode):
    """Runs once after Ascertain closes; produces decomposition, behaviors, plan."""

    name = "decomposition"

    def __init__(
        self,
        events_log: EventsLog,
        agent: DecompositionAgent,
        host_config: HostConfig,
    ) -> None:
        super().__init__(events_log)
        self.agent = agent
        self.host_config = host_config

    async def _run(self, context: PipelineContext) -> PipelineContext:
        project_dir = context.project_dir
        ascertain_path = project_dir / "ascertain.md"

        # 1. Read + parse Ascertain
        ascertain = parse_ascertain(ascertain_path)

        # 2. Emit DECOMPOSITION_STARTED
        await self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.DECOMPOSITION_STARTED,
                payload={"feature_id": ascertain.feature_id, "ascertain_path": str(ascertain_path)},
            )
        )

        # 3. Run Decomposition agent
        agent_output = await self.agent.run(
            ascertain=ascertain, existing_mapping=context.mapping
        )

        # 4. Write decomposition.yaml
        decomposition_path = project_dir / "decomposition.yaml"
        decomposition_data = {
            "schema_version": 1,
            "feature_id": ascertain.feature_id,
            "architecture": agent_output.architecture.model_dump(),
            "behaviors_input": [b.model_dump() for b in agent_output.behaviors],
            "decomposed_at": datetime.now(UTC).isoformat(),
        }
        decomposition_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = decomposition_path.with_suffix(decomposition_path.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(decomposition_data, sort_keys=False), encoding="utf-8")
        tmp.replace(decomposition_path)

        # 5. Enumerate behaviors + write files
        enumeration_result = await enumerate_behaviors(
            agent_output.behaviors,
            context.mapping,
            project_dir,
            self.events_log,
            feature_id=ascertain.feature_id,
        )
        assert isinstance(enumeration_result, tuple)
        updated_mapping, behaviors_path = enumeration_result

        # 6. Generate plan.md content
        template_path = (
            self.host_config.plan_template_path
            if self.host_config.plan_template_path is not None
            else DEFAULT_TEMPLATE_PATH
        )
        new_entries = [
            e for e in updated_mapping.base_bids
            if e.base_bid not in {b.base_bid for b in context.mapping.base_bids}
        ]
        plan_content = render_plan(
            new_entries, ascertain, agent_output.architecture, template_path
        )

        # 7. Approval gate (if required)
        if self.host_config.require_plan_approval:
            # Deferred-tool pause (placeholder — real impl in Plan 6)
            import warnings
            warnings.warn(
                "require_plan_approval=True: deferred-tool prompt not yet wired in Plan 2; "
                "auto-approving for now."
            )

        # 8. Finalize Plan
        assert context.plan_path is not None
        await PlanArtifact.finalize(
            context.plan_path, plan_content, self.events_log
        )

        # 9. Emit DECOMPOSITION_COMPLETED
        await self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.DECOMPOSITION_COMPLETED,
                payload={
                    "feature_id": ascertain.feature_id,
                    "behavior_count": len(new_entries),
                    "plan_path": str(context.plan_path),
                },
            )
        )

        # 10. Return updated context
        return context.model_copy(update={"mapping": updated_mapping})
