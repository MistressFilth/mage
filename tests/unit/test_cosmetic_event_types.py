from mage.orchestration.events import EventType


def test_cosmetic_item_applied_member_exists():
    assert EventType.COSMETIC_ITEM_APPLIED.value == "cosmetic_item_applied"


def test_cosmetic_item_skipped_member_exists():
    assert EventType.COSMETIC_ITEM_SKIPPED.value == "cosmetic_item_skipped"


def test_cosmetic_apply_failed_member_exists():
    assert EventType.COSMETIC_APPLY_FAILED.value == "cosmetic_apply_failed"


def test_cosmetic_refiner_fallback_member_exists():
    assert EventType.COSMETIC_REFINER_FALLBACK.value == "cosmetic_refiner_fallback"
