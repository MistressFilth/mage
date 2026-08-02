"""Decomposition stage: orchestrates agent run, behavior enumeration, plan writing, finalization."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from mage.agents.decomposition import DecompositionAgent
from mage.artifacts.ascertain import parse_ascertain
from mage.artifacts.enumeration import enumerate_behaviors
from mage.artifacts.plan import PlanArtifact, compute_plan_digest
from mage.orchestration.events import Event, EventsLog, EventType
from mage.orchestration.exceptions import StageHalted
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
                payload={
                    "feature_id": ascertain.feature_id,
                    "ascertain_path": str(ascertain_path),
                },
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
        tmp.write_text(
            yaml.safe_dump(decomposition_data, sort_keys=False), encoding="utf-8"
        )
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
        updated_mapping, _behaviors_path = enumeration_result

        # 6. Generate plan.md content
        template_path = (
            self.host_config.plan_template_path
            if self.host_config.plan_template_path is not None
            else DEFAULT_TEMPLATE_PATH
        )
        new_entries = [
            e
            for e in updated_mapping.base_bids
            if e.base_bid not in {b.base_bid for b in context.mapping.base_bids}
        ]
        plan_content = render_plan(
            new_entries, ascertain, agent_output.architecture, template_path
        )

        # 7. Approval gate (if required)
        assert context.plan_path is not None
        await self._approval_gate(
            plan_content=plan_content,
            plan_path=context.plan_path,
            feature_id=ascertain.feature_id,
            project_dir=project_dir,
        )

        # 8. Finalize Plan
        assert context.plan_path is not None
        await PlanArtifact.finalize(context.plan_path, plan_content, self.events_log)

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

    async def _approval_gate(
        self,
        *,
        plan_content: str,
        plan_path: Path,
        feature_id: str,
        project_dir: Path,
    ) -> None:
        """Halt the pipeline until the operator clears the approval marker.

        No-op when require_plan_approval is False. Otherwise:
        - First halt: emit APPROVAL_REQUESTED, write marker, raise StageHalted.
        - Marker present + matching digest: emit APPROVAL_GRANTED, delete marker.
        - Marker absent + prior APPROVAL_REQUESTED in events for current digest:
          emit APPROVAL_GRANTED (operator cleared marker after reviewing).
        - Stale or malformed marker: overwrite with new digest, re-halt.
        """
        if not self.host_config.require_plan_approval:
            return

        plan_digest = compute_plan_digest(plan_content)
        plan_path_rel = plan_path.relative_to(project_dir)
        marker = project_dir / ".mage" / "approval_pending.json"
        pending = self._read_marker(marker)

        if pending is not None and (
            pending.get("_malformed") is True
            or pending.get("plan_digest") != plan_digest
        ):
            # Stale or malformed marker: overwrite and re-halt.
            self._write_marker(
                marker,
                feature_id=feature_id,
                plan_digest=plan_digest,
                plan_path=plan_path_rel,
            )
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.APPROVAL_REQUESTED,
                    payload={
                        "feature_id": feature_id,
                        "plan_digest": plan_digest,
                        "plan_path": str(plan_path_rel),
                    },
                )
            )
            raise StageHalted(
                reason="plan_approval_stale",
                feature_id=feature_id,
                plan_digest=plan_digest,
            )

        if pending is not None:
            # Marker present, digest matches: grant + clear marker.
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.APPROVAL_GRANTED,
                    payload={
                        "feature_id": feature_id,
                        "plan_digest": plan_digest,
                        "approved_by": "human",
                    },
                )
            )
            marker.unlink()
            return

        # No marker: check if a prior APPROVAL_REQUESTED matches current digest.
        prior = self._last_requested_digest(feature_id, plan_digest)
        if prior is not None:
            await self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.APPROVAL_GRANTED,
                    payload={
                        "feature_id": feature_id,
                        "plan_digest": plan_digest,
                        "approved_by": "human",
                    },
                )
            )
            return

        # First halt.
        self._write_marker(
            marker,
            feature_id=feature_id,
            plan_digest=plan_digest,
            plan_path=plan_path_rel,
        )
        await self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.APPROVAL_REQUESTED,
                payload={
                    "feature_id": feature_id,
                    "plan_digest": plan_digest,
                    "plan_path": str(plan_path_rel),
                },
            )
        )
        raise StageHalted(
            reason="plan_approval",
            feature_id=feature_id,
            plan_digest=plan_digest,
        )

    @staticmethod
    def _read_marker(marker: Path) -> dict | None:
        """Read the approval marker file.

        Returns None when absent, a sentinel dict {"_malformed": True} when
        present but unparseable (so the gate treats it as stale), or the
        parsed payload when valid.
        """
        if not marker.exists():
            return None
        import json

        try:
            return json.loads(marker.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"_malformed": True}

    @staticmethod
    def _write_marker(
        marker: Path,
        *,
        feature_id: str,
        plan_digest: str,
        plan_path: Path,
    ) -> None:
        """Atomically write the approval marker file."""
        import json
        import os

        marker.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "feature_id": feature_id,
            "plan_digest": plan_digest,
            "plan_path": str(plan_path),
            "requested_at": datetime.now(UTC).isoformat(),
        }
        tmp = marker.with_suffix(marker.suffix + ".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, marker)

    def _last_requested_digest(self, feature_id: str, plan_digest: str) -> str | None:
        """Return plan_digest if any APPROVAL_REQUESTED matches; else None.

        Looks across the whole events log; the gate runs at most once per
        DecompositionStage run so volume is bounded.
        """
        for event in self.events_log.read_all():
            if (
                event.event_type == EventType.APPROVAL_REQUESTED
                and event.payload.get("feature_id") == feature_id
                and event.payload.get("plan_digest") == plan_digest
            ):
                return plan_digest
        return None
