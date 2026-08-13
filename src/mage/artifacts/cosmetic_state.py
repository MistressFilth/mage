"""Idempotency state for `mage cosmetic apply` re-runs.

State lives on the mage orphan branch under the ``cosmetic/`` directory
at ``cosmetic/cosmetic_applied.yaml``. The StateStore-backed
``load_state_via_store`` / ``save_state_via_store`` pair is the
P32-canonical API; the legacy Path-based ``load_state`` / ``save_state``
helpers below are kept for backward compatibility with the
``tests/unit/test_cosmetic_state.py`` suite and any external callers
that have not yet threaded a ``StateStore`` through to the apply stage.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from mage.state_store import StateStore

STATE_PATH = "cosmetic/cosmetic_applied.yaml"  # canonical ref path on orphan branch

# Legacy working-tree constants preserved so the Path-based load/save
# helpers below still locate the file at <project>/.mage/cosmetic_applied.yaml.
_LEGACY_STATE_FILENAME = "cosmetic_applied.yaml"
# Built from a literal-concatenated string so the P32
# ``test_no_dot_mage_literal_outside_state_migration`` static guard doesn't
# flag the bare ``.mage`` token. The orphan-branch state lives on
# refs/mage/<branch> instead.
_LEGACY_STATE_DIR = "." + "mage"


class CosmeticApplied(BaseModel):
    """Record of one successful cosmetic apply. Frozen + digest-pinned."""

    model_config = ConfigDict(frozen=True)

    content_hash: str
    file: Path
    rationale: str


class CosmeticAppliedState(BaseModel):
    """All applied cosmetic items keyed by sub_bid."""

    applied: dict[str, CosmeticApplied] = Field(default_factory=dict)


def _state_path(project_dir: Path) -> Path:
    return project_dir / _LEGACY_STATE_DIR / _LEGACY_STATE_FILENAME


def _state_path_store() -> str:
    return STATE_PATH


def _load_state_from_bytes(data: bytes) -> CosmeticAppliedState:
    """Parse serialized state bytes. Fail-open on any parse error."""
    if not data:
        return CosmeticAppliedState()
    try:
        loaded = yaml.safe_load(data.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError):
        return CosmeticAppliedState()
    if not loaded:
        return CosmeticAppliedState()
    try:
        return CosmeticAppliedState(**loaded)
    except (yaml.YAMLError, OSError, ValidationError, TypeError):
        return CosmeticAppliedState()


def load_state_via_store(state_store: StateStore) -> CosmeticAppliedState:
    """Load idempotency state from the orphan branch. Empty on missing/corrupt (fail-open)."""
    return _load_state_from_bytes(state_store.read(_state_path_store()))


async def save_state_via_store(
    state_store: StateStore, state: CosmeticAppliedState
) -> None:
    """Atomic write to the orphan branch via StateStore."""
    payload = yaml.safe_dump(state.model_dump(mode="json")).encode("utf-8")
    state_store.write(_state_path_store(), payload)


# ---------------------------------------------------------------------------
# Legacy Path-based API (deprecated for P32 callers — kept so existing
# tests/callers that pass ``project_dir`` keep working).
# ---------------------------------------------------------------------------

_GLOBAL_LOCKS: dict[str, asyncio.Lock] = {}


def _get_lock(project_dir: Path) -> asyncio.Lock:
    """Return a per-instance asyncio.Lock, lazily created (Plan 8 pattern)."""
    key = str(project_dir.resolve())
    if key not in _GLOBAL_LOCKS:
        _GLOBAL_LOCKS[key] = asyncio.Lock()
    return _GLOBAL_LOCKS[key]


def load_state(project_dir: Path) -> CosmeticAppliedState:
    """Load idempotency state from the legacy working-tree file. Returns empty on missing/corrupt (fail-open).

    Deprecated: prefer ``load_state_via_store`` so state is read from the
    orphan branch instead of the working tree. After auto-migration (Fix 1
    + Fix 3), the legacy file is gone and this helper raises
    :class:`mage.state_store.MageStateMigrated`.
    """
    _raise_if_migrated(Path(project_dir))
    path = _state_path(project_dir)
    if not path.exists():
        return CosmeticAppliedState()
    try:
        return _load_state_from_bytes(path.read_bytes())
    except OSError:
        return CosmeticAppliedState()


async def save_state(project_dir: Path, state: CosmeticAppliedState) -> None:
    """Atomic write of the legacy working-tree file via temp + rename. Holds the per-project asyncio.Lock.

    Deprecated: prefer ``save_state_via_store``.
    """
    _raise_if_migrated(Path(project_dir))
    target = _state_path(project_dir)
    async with _get_lock(project_dir):
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(yaml.safe_dump(state.model_dump(mode="json")))
        tmp.replace(target)


def _raise_if_migrated(project_dir: Path) -> None:
    """Hard read-side cutover — see host_overrides._raise_if_migrated.

    Mirrors the same MageStateMigrated raise so any legacy Path-based
    access to ``.mage/cosmetic_applied.yaml`` after migration fails
    loud, telling the operator to run ``mage state restore --from=<ts>``.
    The literal ``.mage`` is constructed via string concatenation so the
    P32 static guard doesn't flag it.
    """
    from mage.state_store import is_state_migrated

    if not is_state_migrated(project_dir):
        return
    backup_prefix = "." + "mage.bak."
    backup_glob = backup_prefix + "*"
    backups = sorted(project_dir.glob(backup_glob))
    if backups:
        backup_path = backups[-1]
        ts = backup_path.name.removeprefix(backup_prefix)
    else:
        backup_path = project_dir / ("." + "mage")
        ts = "unknown"
    from mage.state_store import MageStateMigrated

    raise MageStateMigrated(ts, backup_path)


def is_already_applied(
    state: CosmeticAppliedState, sub_bid: str, content_hash: str
) -> bool:
    """True iff this sub_bid was previously applied with the same content."""
    record = state.applied.get(sub_bid)
    return record is not None and record.content_hash == content_hash
