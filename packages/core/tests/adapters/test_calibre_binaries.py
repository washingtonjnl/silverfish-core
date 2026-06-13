"""Tests for Calibre binary discovery and the secure subprocess wrapper.

Written before the implementation (TDD). Binaries are a system dependency
discovered by env var or OS autodetection; the wrapper always runs argv lists
(never a shell) to avoid command injection, and a health check reports whether
the tools are usable.
"""

import os
import stat
from pathlib import Path

import pytest

from silverfish_core.adapters.calibre_binaries import (
    CalibreBinaries,
    SubprocessRunner,
)


def _make_fake_binary(directory: Path, name: str, *, output: str = "") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    # A tiny executable script that echoes a version-like string.
    path.write_text(f'#!/bin/sh\necho "{output}"\n')
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class TestDiscovery:
    def test_uses_explicit_bin_dir(self, tmp_path: Path) -> None:
        _make_fake_binary(tmp_path, "ebook-convert", output="calibre 8.7")
        _make_fake_binary(tmp_path, "ebook-meta", output="calibre 8.7")
        binaries = CalibreBinaries(bin_dir=tmp_path)
        assert binaries.ebook_convert == tmp_path / "ebook-convert"
        assert binaries.ebook_meta == tmp_path / "ebook-meta"

    def test_missing_binary_is_none(self, tmp_path: Path) -> None:
        _make_fake_binary(tmp_path, "ebook-convert")
        binaries = CalibreBinaries(bin_dir=tmp_path)
        assert binaries.ebook_convert is not None
        assert binaries.ebook_meta is None  # only convert present

    def test_autodetects_from_known_locations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_macos = tmp_path / "calibre.app" / "Contents" / "MacOS"
        _make_fake_binary(fake_macos, "ebook-convert")
        _make_fake_binary(fake_macos, "ebook-meta")
        # No explicit dir: discovery searches a provided list of candidates.
        binaries = CalibreBinaries(bin_dir=None, search_paths=(fake_macos,))
        assert binaries.ebook_convert == fake_macos / "ebook-convert"


class TestHealthCheck:
    def test_available_when_both_present(self, tmp_path: Path) -> None:
        _make_fake_binary(tmp_path, "ebook-convert", output="calibre 8.7")
        _make_fake_binary(tmp_path, "ebook-meta", output="calibre 8.7")
        binaries = CalibreBinaries(bin_dir=tmp_path)
        health = binaries.health()
        assert health.convert_available is True
        assert health.metadata_available is True

    def test_reports_missing(self, tmp_path: Path) -> None:
        binaries = CalibreBinaries(bin_dir=tmp_path)  # empty dir
        health = binaries.health()
        assert health.convert_available is False
        assert health.metadata_available is False


class TestSubprocessRunner:
    def test_runs_argv_and_captures_output(self) -> None:
        runner = SubprocessRunner()
        result = runner.run(["/bin/echo", "hello world"])
        assert result.returncode == 0
        assert "hello world" in result.stdout

    def test_nonzero_return_code_is_reported(self) -> None:
        runner = SubprocessRunner()
        result = runner.run(["/bin/sh", "-c", "exit 3"])
        assert result.returncode == 3

    def test_argv_is_not_shell_interpreted(self, tmp_path: Path) -> None:
        # A shell metacharacter passed as one argv element must be literal, not
        # interpreted — proof we never use shell=True.
        marker = tmp_path / "pwned"
        runner = SubprocessRunner()
        runner.run(["/bin/echo", f"; touch {marker}"])
        assert not marker.exists()

    def test_timeout_raises(self) -> None:
        runner = SubprocessRunner()
        with pytest.raises(TimeoutError):
            runner.run(["/bin/sh", "-c", "sleep 5"], timeout=0.2)

    def test_missing_executable_raises(self) -> None:
        runner = SubprocessRunner()
        with pytest.raises((FileNotFoundError, OSError)):
            runner.run([str(Path(os.sep) / "no" / "such" / "binary")])
