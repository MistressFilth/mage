"""mage: spec-driven development pipeline."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mage")
except PackageNotFoundError:  # pragma: no cover - source tree without install
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
