"""CLI filter parsing for `mage cosmetic` subcommands.

This round supports only the `sub_bid=...` key. Unknown keys, missing
`=`, and empty values all raise `FilterParseError`. Single key, single
value per occurrence; duplicates collapse silently.
"""

from __future__ import annotations


class FilterParseError(Exception):
    """Raised when `--filter` arguments cannot be parsed.

    The `subcommand` field stores the cosmetic subcommand name (without
    spaces) so callers can produce the spec-required error line:

        mage cosmetic <sub>: <message>
    """

    def __init__(self, message: str, *, subcommand: str) -> None:
        super().__init__(message)
        self.subcommand = subcommand
        self.message = message


_KNOWN_KEYS: frozenset[str] = frozenset({"sub_bid"})


def parse_filters(
    raw: list[str] | None,
    *,
    subcommand: str = "cosmetic",
) -> dict[str, set[str]]:
    """Return a `{key: set(values)}` map from a list of `--filter k=v` strings.

    Empty / `None` input returns `{}` (caller interprets this as "no
    narrowing"). Raises `FilterParseError` on malformed input.
    """
    if not raw:
        return {}
    out: dict[str, set[str]] = {}
    for item in raw:
        if "=" not in item:
            raise FilterParseError(
                f"malformed filter {item!r}; expected 'key=value'",
                subcommand=subcommand,
            )
        key, value = item.split("=", 1)
        if not key:
            raise FilterParseError(
                "empty filter key",
                subcommand=subcommand,
            )
        if key not in _KNOWN_KEYS:
            raise FilterParseError(
                f"unknown filter key {item!r}",
                subcommand=subcommand,
            )
        if not value:
            raise FilterParseError(
                f"empty filter value for key {key!r}",
                subcommand=subcommand,
            )
        out.setdefault(key, set()).add(value)
    return out
