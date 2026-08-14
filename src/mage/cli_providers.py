"""CLI handlers for ``mage providers``."""

from __future__ import annotations

from mage.providers.probe import ProbeResult

__all__: list[str] = []

_GLYPH_OK = "✓"
_GLYPH_WARN = "⚠"
_GLYPH_FAIL = "✗"


def _glyph(result: ProbeResult) -> str:
    if not result.network_ok:
        return _GLYPH_FAIL
    if result.default_model_present is False:
        return _GLYPH_WARN
    return _GLYPH_OK


def _tail(result: ProbeResult) -> str:
    if not result.network_ok:
        return result.error or "unknown error"
    if result.default_model_present is False:
        return f"{result.default_model} missing   {result.latency_ms}ms   {len(result.models)} models"
    model = result.default_model or "-"
    return f"{model} present   {result.latency_ms}ms   {len(result.models)} models"


def _format_human(results: list[ProbeResult]) -> str:
    lines: list[str] = []
    name_width = max((len(r.name) for r in results), default=6)
    url_width = max((len(r.base_url or "-") for r in results), default=1)
    for r in results:
        lines.append(
            f"{_glyph(r)} {r.name:<{name_width}}  {(r.base_url or '-'):<{url_width}}  {_tail(r)}"
        )
    ok_count = sum(1 for r in results if r.network_ok)
    lines.append(f"{ok_count} ok, {len(results) - ok_count} failed")
    return "\n".join(lines)


def _format_json(results: list[ProbeResult]) -> dict[str, object]:
    return {
        "ok": all(r.network_ok for r in results),
        "providers": [r.model_dump() for r in results],
    }
