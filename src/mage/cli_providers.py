"""CLI handlers for ``mage providers``."""

from __future__ import annotations

import json as _json
import sys
from typing import Literal

from mage.providers.config import load_xdg_providers
from mage.providers.probe import ProbeResult, probe_provider

__all__ = ["test_providers"]

# Tell pytest not to collect from this module: ``test_providers`` matches the
# default ``python_functions = test_*`` pattern, and re-exporting it via
# ``from mage.cli_providers import test_providers`` would otherwise make the
# public function appear as a stray collected test.
__test__ = False

Format = Literal["human", "json"]

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


def test_providers(fmt: str) -> int:
    """Probe every configured provider. Returns process exit code."""
    if fmt not in ("human", "json"):
        raise ValueError(f"unknown format: {fmt!r}")

    providers, _default = load_xdg_providers()
    results = [probe_provider(name, cfg) for name, cfg in sorted(providers.items())]

    if fmt == "json":
        sys.stdout.write(_json.dumps(_format_json(results), indent=2) + "\n")
    else:
        sys.stdout.write(_format_human(results) + "\n")

    return 0 if all(r.network_ok for r in results) else 1


# Mark the public aggregator as not-a-test even though its name matches the
# default ``python_functions = test_*`` pattern. Without this, ``from
# mage.cli_providers import test_providers`` re-exports the name into the
# importing test module's namespace and pytest collects it as a stray test
# that fails because ``fmt`` is not a fixture.
test_providers.__test__ = False  # type: ignore[attr-defined, ty:unresolved-attribute]
