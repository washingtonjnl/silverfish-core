"""Silverfish core library.

Domain rules, ports (interfaces), services (use cases) and reference adapters
for managing an ebook library in the Calibre dialect. This package contains no
web nor concrete-persistence code at its boundary: those are plugged in via
adapters by whoever consumes the core.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("silverfish-core")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0"
