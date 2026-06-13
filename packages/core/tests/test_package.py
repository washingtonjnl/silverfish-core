"""Smoke test for the core package scaffolding."""

import silverfish_core


def test_core_exposes_version() -> None:
    assert silverfish_core.__version__ == "0.0.0"
