import asyncio
from datetime import UTC, datetime
from pathlib import Path

from mage.orchestration.events import Event, EventType, EventsLog


def _evt(ts: int) -> Event:
    return Event(timestamp=datetime(2026, 7, 29, 12, 0, ts, tzinfo=UTC), event_type=EventType.STAGE_STARTED, payload={"i": ts})


def test_concurrent_appends_serialize(tmp_path: Path):
    async def run() -> None:
        log = EventsLog(tmp_path / "events.jsonl")
        await asyncio.gather(*[log.append(_evt(i)) for i in range(10)])
        lines = (tmp_path / "events.jsonl").read_text().splitlines()
        assert len(lines) == 10
        payloads = [Event.model_validate_json(line).payload for line in lines]
        assert sorted(p["i"] for p in payloads) == list(range(10))

    asyncio.run(run())


def test_reads_unaffected_by_writes(tmp_path: Path):
    async def run() -> None:
        log = EventsLog(tmp_path / "events.jsonl")
        await log.append(_evt(0))
        snapshot_during = log.read_all()
        await log.append(_evt(1))
        snapshot_after = log.read_all()
        assert len(snapshot_during) == 1
        assert len(snapshot_after) == 2

    asyncio.run(run())



def test_reads_stay_sync(tmp_path: Path):
    log = EventsLog(tmp_path / "events.jsonl")
    asyncio.run(log.append(_evt(0)))
    assert len(log.read_all()) == 1
    assert len(log.read_since(datetime(2026, 7, 28, tzinfo=UTC))) == 1

