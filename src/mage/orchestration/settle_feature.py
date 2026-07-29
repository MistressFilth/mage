"""SettleFeature stage: cosmetic queue handoff + finishing-equivalent finalization."""

from __future__ import annotations

from datetime import UTC, datetime

from mage.orchestration.events import Event, EventType, EventsLog
from mage.orchestration.nodes import PipelineContext, StageNode


class SettleFeatureStage(StageNode):
    """Aggregate cosmetics, write a settle report, and record finalization.

    Settle does not review; review is InspectFeatureStage's responsibility.
    """

    name = "settle_feature"

    def __init__(self, events_log: EventsLog) -> None:
        super().__init__(events_log)

    def _run(self, context: PipelineContext) -> PipelineContext:  # noqa: ARG002
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_COMPLETED,
                payload={"stub": True},
            )
        )
        return context

    def run_settle(
        self,
        context: PipelineContext,
        *,
        feature_id: str,
        disposition: str,
    ) -> None:
        """Write cosmetic and settle reports for the chosen disposition."""
        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_STARTED,
                payload={
                    "feature_id": feature_id,
                    "cosmetic_queue_size": len(
                        context.mapping.feature_cosmetic_queue
                    ),
                },
            )
        )

        queue = context.mapping.feature_cosmetic_queue
        cosmetic_path = (
            context.project_dir / ".haileris" / "settle" / f"{feature_id}-cosmetic.md"
        )
        cosmetic_path.parent.mkdir(parents=True, exist_ok=True)
        cosmetic_path.write_text(self._render_cosmetic_md(queue), encoding="utf-8")

        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_COSMETIC_QUEUED,
                payload={"feature_id": feature_id, "queue_size": len(queue)},
            )
        )

        report_md = (
            f"# Settle Feature {feature_id}\n\n"
            f"## Disposition\n\n{disposition}\n\n"
            f"## Cosmetic Queue ({len(queue)} items)\n\n"
            f"See `{feature_id}-cosmetic.md` for the full list.\n\n"
            f"## Finalized at\n\n{datetime.now(UTC).isoformat()}\n"
        )
        report_path = context.project_dir / ".haileris" / "settle" / f"{feature_id}.md"
        report_path.write_text(report_md, encoding="utf-8")

        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_FINALIZED,
                payload={"feature_id": feature_id, "disposition": disposition},
            )
        )

        if disposition == "discarded":
            self.events_log.append(
                Event(
                    timestamp=datetime.now(UTC),
                    event_type=EventType.SETTLE_BRANCH_DISCARDED,
                    payload={"feature_id": feature_id},
                )
            )

        self.events_log.append(
            Event(
                timestamp=datetime.now(UTC),
                event_type=EventType.SETTLE_FEATURE_COMPLETED,
                payload={"feature_id": feature_id, "disposition": disposition},
            )
        )

    @staticmethod
    def _render_cosmetic_md(queue: list[dict]) -> str:
        """Render queued cosmetic findings as markdown."""
        if not queue:
            return "# Cosmetic Queue\n\n(empty)\n"
        lines = ["# Cosmetic Queue", ""]
        for i, item in enumerate(queue, 1):
            lines.append(
                f"{i}. **{item.get('sub_bid', '?')}** / {item.get('scenario_name', '?')} "
                f"({item.get('proposed_by', '?')})\n"
                f"   - location: {item.get('location', '?')}\n"
                f"   - text: {item.get('text', '?')}\n"
            )
        return "\n".join(lines)
