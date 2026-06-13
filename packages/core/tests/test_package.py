"""Smoke test for the core package scaffolding."""

import silverfish_core


def test_core_exposes_version() -> None:
    # Version is derived from the git tag; assert it is a non-empty PEP 440-ish
    # string rather than a hardcoded literal.
    assert isinstance(silverfish_core.__version__, str)
    assert silverfish_core.__version__
    assert silverfish_core.__version__[0].isdigit()
