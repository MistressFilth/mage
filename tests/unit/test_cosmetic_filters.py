"""Cosmetic filter parser contract tests."""

from __future__ import annotations

import pytest

from mage.cosmetic_filters import FilterParseError, parse_filters


class TestParseFilters:
    def test_none_returns_empty(self) -> None:
        assert parse_filters(None) == {}

    def test_empty_list_returns_empty(self) -> None:
        assert parse_filters([]) == {}

    def test_single_sub_bid(self) -> None:
        assert parse_filters(["sub_bid=01JF..."]) == {"sub_bid": {"01JF..."}}

    def test_multi_sub_bid_dedups(self) -> None:
        result = parse_filters(
            ["sub_bid=01JF...", "sub_bid=01JF...", "sub_bid=01JG..."]
        )
        assert result == {"sub_bid": {"01JF...", "01JG..."}}

    @pytest.mark.parametrize(
        "raw,reason",
        [
            ("01JF...", "missing '='"),
            ("sub_bid=", "empty value"),
            ("=01JF...", "empty key"),
            ("file=src/x.py", "unknown key"),
        ],
    )
    def test_rejects_malformed(self, raw: str, reason: str) -> None:
        with pytest.raises(FilterParseError) as exc:
            parse_filters([raw])
        rendered = str(exc.value)
        assert raw in rendered or "empty" in rendered.lower()


class TestFilterParseError:
    def test_carries_subcommand(self) -> None:
        err = FilterParseError("bad", subcommand="cosmeticlist")
        assert err.subcommand == "cosmeticlist"
        assert "bad" in str(err)
