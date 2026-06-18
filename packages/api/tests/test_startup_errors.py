"""Tests for friendly startup failures (TDD).

A misconfiguration at boot (e.g. calibre mode pointed at a folder with no
metadata.db) is the user's to fix, not a bug. The app must fail with a clear,
single-line message — not a 30-line traceback that buries the cause. We assert
the message is logged and that startup still aborts.
"""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import StartupError, create_app


@pytest.fixture
def empty_calibre_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    # Calibre mode, but the directory has no metadata.db.
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(tmp_path))
    monkeypatch.setenv("SILVERFISH_LIBRARY_MODE", "calibre")
    yield tmp_path


class TestCalibreMisconfiguration:
    def test_startup_aborts(self, empty_calibre_dir: Path) -> None:
        # Entering the app (running the lifespan) must fail, not start serving.
        with pytest.raises(StartupError), TestClient(create_app()):
            pass

    def test_logs_a_clear_single_message(
        self, empty_calibre_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with (
            caplog.at_level(logging.ERROR),
            pytest.raises(StartupError),
            TestClient(create_app()),
        ):
            pass
        messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
        joined = "\n".join(messages)
        # The cause is stated in plain words, mentioning the offending path.
        assert "metadata.db" in joined
        assert str(empty_calibre_dir) in joined
        # And it reads as guidance, not a stack dump.
        assert "Traceback" not in joined
