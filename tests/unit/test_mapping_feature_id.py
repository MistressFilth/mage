from pathlib import Path

import pytest
from pydantic import ValidationError

from mage.artifacts.cosmetic import CosmeticItem
from mage.artifacts.mapping import MappingArtifact


def test_feature_cosmetic_queue_entry_requires_feature_id():
    with pytest.raises(ValidationError):
        MappingArtifact(
            schema_version=2,
            project_id="p",
            feature_cosmetic_queue=[
                {
                    "sub_bid": "00000-001",
                    "text": "use a constant",
                    # NO feature_id
                }
            ],
        )


def test_append_cosmetic_takes_feature_id_and_appends():
    m = MappingArtifact(schema_version=2, project_id="p")
    item = CosmeticItem(
        sub_bid="00000-001",
        file_path=Path("src/example.py"),
        line_range=(10, 20),
        replacement_text="x = 42\n",
        rationale="use a constant",
        proposed_by="human",
    )
    m2 = m.append_cosmetic("feat-1", item)
    assert len(m2.feature_cosmetic_queue) == 1
    assert m2.feature_cosmetic_queue[0]["feature_id"] == "feat-1"


def test_feature_cosmetic_queue_round_trips_via_save_load(tmp_path):
    m = MappingArtifact(schema_version=2, project_id="p")
    item = CosmeticItem(
        sub_bid="00000-001",
        file_path=Path("src/example.py"),
        line_range=(1, 1),
        replacement_text="x\n",
        rationale="x",
        proposed_by="human",
    )
    m2 = m.append_cosmetic("feat-9", item)
    path = tmp_path / "mapping.yaml"
    import asyncio

    asyncio.run(m2.save(path))
    loaded = MappingArtifact.load(path)
    assert loaded.feature_cosmetic_queue[0]["feature_id"] == "feat-9"


def test_feature_cosmetic_queue_accepts_empty_feature_id_string():
    """Plan 13: empty-string feature_id is a valid (back-compat) value, distinct from the key being omitted.

    The "key omitted" case still raises via Plan 10's strict validator. An explicit
    empty-string value is the documented Plan 12 default when the caller's
    feature_id is unset, so load() must accept it.
    """
    MappingArtifact(
        schema_version=2,
        project_id="p",
        feature_cosmetic_queue=[
            {
                "feature_id": "",
                "sub_bid": "00000-001",
                "text": "use a constant",
            }
        ],
    )  # no raise


def test_feature_cosmetic_queue_empty_feature_id_round_trips(tmp_path):
    """load() preserves an empty-string feature_id (no fallback to 'unknown', no raise)."""
    m = MappingArtifact(schema_version=2, project_id="p", feature_cosmetic_queue=[
        {"feature_id": "", "sub_bid": "00000-001", "text": "use a constant"}
    ])
    path = tmp_path / "mapping.yaml"
    import asyncio
    asyncio.run(m.save(path))
    loaded = MappingArtifact.load(path)
    assert loaded.feature_cosmetic_queue[0]["feature_id"] == ""
