"""Shared test fixtures for the API tests.

Tests must not read a developer's real ``.env``/``.env.local`` (which could set
SMTP, a library dir, etc. and make results machine-dependent). This autouse
fixture runs every test from a clean temporary directory so settings come only
from each test's explicit env vars.
"""

import pytest


@pytest.fixture(autouse=True)
def _isolate_env_files(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    clean_dir = tmp_path_factory.mktemp("cwd")
    monkeypatch.chdir(clean_dir)
