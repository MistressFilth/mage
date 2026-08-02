from pathlib import Path

import pytest
from pydantic import ValidationError

from mage.artifacts.cosmetic import CosmeticPatch


def _item(**overrides):
    defaults = {
        "sub_bid": "00000-001",
        "file_path": Path("src/example.py"),
        "line_range": (10, 20),
        "replacement_text": "new code\n",
        "rationale": "use a constant",
        "proposed_by": "IncrementQualityReviewer",
    }
    defaults.update(overrides)
    return CosmeticPatch(**defaults)


def test_cosmetic_item_content_hash_stable():
    item_a = _item()
    item_b = _item()
    assert item_a.content_hash == item_b.content_hash
    assert len(item_a.content_hash) == 64  # sha256 hex


def test_cosmetic_item_content_hash_changes_with_replacement():
    item_a = _item()
    item_b = _item(replacement_text="different\n")
    assert item_a.content_hash != item_b.content_hash


def test_cosmetic_item_validates_line_range_order():
    with pytest.raises(ValidationError):
        _item(line_range=(20, 10))
