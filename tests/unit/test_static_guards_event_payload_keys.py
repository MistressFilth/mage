"""Static-guard regression net for event-payload key spellings.

Closes the Plan 19 deferred follow-up (TODO.md:46). Pins the
`EventType.MAPPING_SAVED` payload-key set so a typo at the lone emit
site (`src/mage/artifacts/mapping.py:288-297`) is caught by `make test`
rather than silently admitted by the `dict` payload type.

Mirrors the Plan 17/15 grep/ast-over-`src/mage/` pattern used by
`tests/unit/test_static_guards_plan17.py` and friends.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "mage"

EXPECTED_MAPPING_SAVED_KEYS: frozenset[str] = frozenset(
    {
        "feature_cosmetic_queue_size",
        "base_bids_count",
    }
)


def _payload_dict_keys(node: ast.Dict) -> frozenset[str] | None:
    """Return the str-key set of a dict literal, or None if any key is non-string."""
    keys: set[str] = set()
    for key in node.keys:
        if key is None:
            return None  # **kwargs spread — not a static literal dict
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            return None
        keys.add(key.value)
    return frozenset(keys)


def _is_mappingsaved_event_call(call: ast.Call) -> tuple[ast.Dict | None, int]:
    """Return (payload_dict_node_or_None, line_number) if `call` is an
    `Event(event_type=EventType.MAPPING_SAVED, payload={...})` construction.

    Returns (None, line_no) if the call is an `Event` call but the
    `event_type` is not MAPPING_SAVED (so the walker can short-circuit).
    Returns (None, 0) for non-Event calls.
    """
    # Match `Event(...)` (Name) or `<expr>.Event(...)` (Attribute).
    func = call.func
    func_name: str | None
    if isinstance(func, ast.Name):
        func_name = func.id
    elif isinstance(func, ast.Attribute):
        func_name = func.attr
    else:
        return (None, 0)
    if func_name != "Event":
        return (None, 0)

    event_type_node: ast.AST | None = None
    payload_node: ast.AST | None = None
    for kw in call.keywords:
        if kw.arg == "event_type":
            event_type_node = kw.value
        elif kw.arg == "payload":
            payload_node = kw.value

    if event_type_node is None:
        return (None, call.lineno)
    if not (
        isinstance(event_type_node, ast.Attribute)
        and isinstance(event_type_node.value, ast.Name)
        and event_type_node.value.id == "EventType"
        and event_type_node.attr == "MAPPING_SAVED"
    ):
        return (None, call.lineno)

    if isinstance(payload_node, ast.Dict):
        return (payload_node, call.lineno)
    return (None, call.lineno)


def _walk_mappingsaved_emits() -> list[tuple[Path, int, frozenset[str] | None]]:
    """Walk every `src/mage/**/*.py` file and return one tuple per
    MAPPING_SAVED-typed Event call: (file, lineno, payload_keys_or_None).

    `payload_keys_or_None` is None when the call has `event_type =
    EventType.MAPPING_SAVED` but its `payload` kwarg is not a literal
    dict of str keys — the third test asserts this shape is preserved.
    """
    results: list[tuple[Path, int, frozenset[str] | None]] = []
    for py_file in sorted(SRC.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            payload_dict, lineno = _is_mappingsaved_event_call(node)
            if lineno == 0:
                continue
            if payload_dict is None:
                # Matched an Event call but not a MAPPING_SAVED emit — skip.
                continue
            keys = _payload_dict_keys(payload_dict)
            results.append((py_file, lineno, keys))
    return results


def test_mappingsaved_payload_keys_match_expected() -> None:
    """Every MAPPING_SAVED emit must carry exactly the expected payload keys."""
    emits = _walk_mappingsaved_emits()
    assert emits, (
        "expected at least one MAPPING_SAVED emit site under src/mage; "
        "found none. The static guard has nothing to pin."
    )
    for file, lineno, keys in emits:
        assert keys == EXPECTED_MAPPING_SAVED_KEYS, (
            f"MAPPING_SAVED payload keys at {file}:{lineno} do not match.\n"
            f"  expected: {sorted(EXPECTED_MAPPING_SAVED_KEYS)}\n"
            f"  actual:   {sorted(keys or ())}\n"
            f"  missing:  {sorted(EXPECTED_MAPPING_SAVED_KEYS - (keys or frozenset()))}\n"
            f"  extra:    {sorted((keys or frozenset()) - EXPECTED_MAPPING_SAVED_KEYS)}\n"
            "Update EXPECTED_MAPPING_SAVED_KEYS in this file if the change is intentional."
        )


def test_mappingsaved_emit_site_count_is_one() -> None:
    """Exactly one MAPPING_SAVED emit site must exist under src/mage/."""
    emits = _walk_mappingsaved_emits()
    sites = [(f, l) for f, l, _ in emits]
    assert len(emits) == 1, (
        f"expected exactly one MAPPING_SAVED emit site under src/mage; "
        f"found {len(emits)}: {sites}"
    )


def test_mappingsaved_payload_is_literal_dict() -> None:
    """Every MAPPING_SAVED emit must pass a literal dict of str keys as payload.

    This is the structural precondition that lets the AST walker compare
    key sets without evaluating code. If a future emit uses kwargs unpack,
    a Pydantic model, or a dynamically-built dict, this test fails and
    forces the static shape to be preserved (or the walker upgraded).
    """
    bad_sites: list[tuple[Path, int]] = []
    for py_file in sorted(SRC.rglob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            payload_dict, lineno = _is_mappingsaved_event_call(node)
            if lineno == 0 or payload_dict is None:
                continue
            keys = _payload_dict_keys(payload_dict)
            if keys is None:
                bad_sites.append((py_file, lineno))
    assert not bad_sites, (
        "MAPPING_SAVED emits below use a non-literal-dict payload; "
        "the static guard requires a literal dict of str keys:\n"
        + "\n".join(f"  {f}:{l}" for f, l in bad_sites)
    )
