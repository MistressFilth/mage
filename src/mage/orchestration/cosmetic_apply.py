"""Apply cosmetic queue items for a single feature.

Extracted from cmd_cosmetic_apply (Plan 11 Task 3) so the watcher daemon
can reuse it. CLI behavior is byte-identical to the pre-extraction
implementation.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

from mage.host_project_config import load_mage_toml, resolve_model_logged
from mage.orchestration.events import Event, EventsLog, EventType
from mage.providers.config import load_xdg_providers
from mage.state_store import StateStore, state_store_for
from mage.verification.host_overrides import load_host_config


async def apply_for_feature(
    project_dir: Path,
    sub_bids: list[str],
    *,
    dry_run: bool = False,
    feature_id: str | None = None,
    state_store: StateStore | None = None,
) -> int:
    """Apply cosmetic queue items for the given sub_bids.

    The cosmetic watcher passes `feature_id=<per-feature fid>` so a
    sub_bid shared between features is processed under its correct
    feature only. The CLI pass supplies `args.feature_id` (a required
    positional) and the available sub_bids are pre-filtered to that
    feature in `cmd_cosmetic_apply` before reaching this function.

    ``state_store`` is required for production (mapping lives on the
    orphan branch after P32 task 10). When ``None``, the factory fallback
    builds one via ``state_store_for(project_dir, load_mage_toml(...))``
    so the API stays ergonomic for ad-hoc CLI/test use.

    Returns 0 on success (including no-op when the requested set is empty
    or all entries resolve to a no-op), 1 if the mapping is empty/absent
    on the orphan branch.
    """
    from mage.agents.cosmetic_refiner import CosmeticRefiner
    from mage.artifacts.cosmetic_state import (
        CosmeticApplied,
        is_already_applied,
        load_state,
        save_state,
    )
    from mage.artifacts.mapping import MappingArtifact

    log = EventsLog(project_dir / "events.jsonl")
    if state_store is None:
        # P32: the working-tree mapping.yaml is no longer authoritative;
        # construct the orphan-branch store from mage.toml. This matches
        # the watcher-side fallback so a missed `state_store=` arg still
        # hits the right storage.
        state_store = state_store_for(project_dir, load_mage_toml(project_dir))
    # P32: a fresh project has no mapping on the orphan branch yet;
    # load_from_state_store returns the canonical empty artifact in that
    # case, and the empty queue makes this a no-op (rc=0). The legacy
    # "no mapping found" guard is gone — empty mapping IS the first-run
    # state on the orphan branch, same as `cmd_cosmetic_apply`.
    mapping = MappingArtifact.load_from_state_store(state_store)
    host_config = load_host_config(project_dir)
    mage_toml = load_mage_toml(project_dir)
    providers, default_provider = load_xdg_providers()
    model, _, _ = await resolve_model_logged(
        mage_toml,
        "cosmetic_refiner",
        providers=providers,
        default_provider=default_provider,
        env=dict(os.environ),
        events_log=log,
    )
    refiner = CosmeticRefiner(model=model)
    semaphore = asyncio.Semaphore(host_config.max_concurrent_llm_calls)
    wanted = set(sub_bids)
    queue = [
        q
        for q in mapping.cosmetic_findings
        if q.get("sub_bid") in wanted
        and (feature_id is None or q.get("feature_id") == feature_id)
    ]
    if not queue:
        return 0
    refined = await asyncio.gather(
        *[refiner.refine(q, semaphore=semaphore) for q in queue]
    )

    now = datetime.now(UTC)
    state = load_state(project_dir)
    for item in refined:
        if item.file_path is None:
            await log.append(
                Event(
                    timestamp=now,
                    event_type=EventType.COSMETIC_REFINER_FALLBACK,
                    payload={"sub_bid": item.sub_bid, "rationale": item.rationale},
                )
            )
            continue
        if is_already_applied(state, item.sub_bid, item.content_hash):
            await log.append(
                Event(
                    timestamp=now,
                    event_type=EventType.COSMETIC_ITEM_SKIPPED,
                    payload={"sub_bid": item.sub_bid, "reason": "already-applied"},
                )
            )
            continue
        target = project_dir / item.file_path
        if not target.exists():
            await log.append(
                Event(
                    timestamp=now,
                    event_type=EventType.COSMETIC_APPLY_FAILED,
                    payload={"sub_bid": item.sub_bid, "reason": "file-missing"},
                )
            )
            continue
        try:
            lines = target.read_text().splitlines()
            new_lines = (
                lines[: item.line_range[0] - 1]
                + item.replacement_text.splitlines()
                + lines[item.line_range[1] :]
            )
            if not dry_run:
                target.write_text("\n".join(new_lines) + "\n")
                try:
                    await asyncio.to_thread(
                        subprocess.run,
                        [
                            "git",
                            "commit",
                            "-am",
                            f"cosmetic({item.sub_bid}): {item.rationale}",
                        ],
                        cwd=str(project_dir),
                        check=True,
                        timeout=30,
                    )
                except subprocess.TimeoutExpired:
                    await log.append(
                        Event(
                            timestamp=now,
                            event_type=EventType.COSMETIC_APPLY_FAILED,
                            payload={
                                "sub_bid": item.sub_bid,
                                "reason": "git-timeout",
                                "error_type": "TimeoutExpired",
                            },
                        )
                    )
                    continue
            if not dry_run:
                state.applied[item.sub_bid] = CosmeticApplied(
                    content_hash=item.content_hash,
                    file=item.file_path,  # type: ignore[arg-type]
                    rationale=item.rationale,
                )
                try:
                    await save_state(project_dir, state)
                except (yaml.YAMLError, OSError) as exc:
                    await log.append(
                        Event(
                            timestamp=now,
                            event_type=EventType.COSMETIC_APPLY_FAILED,
                            payload={
                                "sub_bid": item.sub_bid,
                                "reason": "state-save-failed",
                                "error_type": type(exc).__name__,
                            },
                        )
                    )
                    continue
            await log.append(
                Event(
                    timestamp=now,
                    event_type=EventType.COSMETIC_ITEM_APPLIED
                    if not dry_run
                    else EventType.COSMETIC_ITEM_SKIPPED,
                    payload={
                        "sub_bid": item.sub_bid,
                        "file": Path(item.file_path).as_posix(),
                    },
                )
            )
        except (yaml.YAMLError, OSError, subprocess.CalledProcessError) as exc:
            await log.append(
                Event(
                    timestamp=now,
                    event_type=EventType.COSMETIC_APPLY_FAILED,
                    payload={
                        "sub_bid": item.sub_bid,
                        "reason": str(exc),
                        "error_type": type(exc).__name__,
                    },
                )
            )
    return 0
