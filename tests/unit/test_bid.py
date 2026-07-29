"""Tests for the Base85 BID module."""

from __future__ import annotations

import pytest
from mage.artifacts.bid import Base85BID, next_base_bid


class TestBase85BID:
    def test_construct_from_5_digit_string(self):
        bid = Base85BID(value="00000")
        assert bid.value == "00000"

    def test_construct_rejects_invalid_chars(self):
        with pytest.raises(ValueError, match="invalid Base85 character"):
            Base85BID(value="0000 ")  # space not in alphabet

    def test_increment_00000_to_00001(self):
        bid = Base85BID(value="00000")
        incremented = bid.increment()
        assert incremented.value == "00001"

    def test_increment_rolls_over_at_alphabet_end(self):
        # 84 is the highest 2-digit value in Base85 (alphabet has 85 chars)
        bid = Base85BID(value="0000z")  # 'z' is index 57, not the end
        # Use the highest possible 5-digit Base85 value
        max_bid = Base85BID(value="~~~~~")  # '~' is the last char in alphabet (index 84)
        with pytest.raises(OverflowError, match="exhausted"):
            max_bid.increment()

    def test_increment_is_monotonic(self):
        a = Base85BID(value="00005")
        b = a.increment()
        c = b.increment()
        assert a.value < b.value < c.value

    def test_parse_classmethod(self):
        bid = Base85BID.parse("00042")
        assert bid.value == "00042"

    def test_parse_rejects_invalid(self):
        with pytest.raises(ValueError, match="invalid Base85 character"):
            Base85BID.parse("0004 ")


def test_derive_sub_bid_with_index_zero():
    from mage.artifacts.bid import Base85BID
    parent = Base85BID(value="00000")
    sub = Base85BID.derive(parent, 0)
    assert sub.value == "00000" + "0"  # parent + '0' = first scenario


def test_derive_sub_bid_with_index_84():
    from mage.artifacts.bid import Base85BID
    parent = Base85BID(value="00001")
    sub = Base85BID.derive(parent, 84)
    # index 84 → single char '~' (last in alphabet)
    assert sub.value == "00001~"


def test_derive_sub_bid_with_index_85():
    from mage.artifacts.bid import Base85BID
    parent = Base85BID(value="00010")
    sub = Base85BID.derive(parent, 85)
    # index 85 → two chars: "01" (since 85 = 1*85 + 0)
    assert sub.value == "00010" + "10"


def test_derive_sub_bid_rejects_negative_index():
    from mage.artifacts.bid import Base85BID
    parent = Base85BID(value="00000")
    import pytest
    with pytest.raises(ValueError, match="non-negative"):
        Base85BID.derive(parent, -1)


class TestNextBaseBid:
    def test_next_from_zero(self):
        # No BIDs assigned yet; next is "00000"
        next_bid = next_base_bid(highest=None)
        assert next_bid.value == "00000"

    def test_next_from_existing(self):
        highest = Base85BID(value="00042")
        next_bid = next_base_bid(highest=highest)
        assert next_bid.value == "00043"

    def test_next_handles_max_value(self):
        max_bid = Base85BID(value="~~~~~")
        with pytest.raises(OverflowError, match="exhausted"):
            next_base_bid(highest=max_bid)