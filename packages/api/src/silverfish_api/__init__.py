"""Silverfish API — thin FastAPI layer over the core.

This package only translates HTTP to/from core services and produces the OpenAPI
contract used to generate client SDKs. It holds no domain logic.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("silverfish-api")
except PackageNotFoundError:  # pragma: no cover - only when not installed
    __version__ = "0.0.0"
