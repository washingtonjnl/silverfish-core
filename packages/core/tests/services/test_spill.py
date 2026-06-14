"""Tests for the named-temp-file spill helper.

Written before the implementation (TDD). When data is written to a temp file for
a path-based extractor, the temp file keeps the *original* base name (so a tool
that falls back to the filename as title gets a real name, not 'tmpXXXX'). The
file lives in a unique temp dir and is removed on exit.
"""

from pathlib import Path

from silverfish_core.services.spill import spill_named


class TestSpillNamed:
    def test_writes_data_and_yields_path(self) -> None:
        with spill_named(b"hello", base_name="My Book", suffix=".pdf") as path:
            assert path.read_bytes() == b"hello"

    def test_filename_uses_base_name_and_suffix(self) -> None:
        with spill_named(b"x", base_name="The Great Book", suffix=".epub") as path:
            assert path.name == "The Great Book.epub"

    def test_sanitises_base_name(self) -> None:
        with spill_named(b"x", base_name="a/b:c", suffix=".pdf") as path:
            # No path separators leak into the filename.
            assert "/" not in path.name
            assert path.suffix == ".pdf"

    def test_falls_back_when_base_name_empty(self) -> None:
        with spill_named(b"x", base_name="", suffix=".pdf") as path:
            assert path.suffix == ".pdf"
            assert path.name  # some non-empty name

    def test_cleans_up_on_exit(self) -> None:
        with spill_named(b"x", base_name="Book", suffix=".pdf") as path:
            saved = path
            parent = path.parent
        assert not saved.exists()
        assert not parent.exists()  # the unique temp dir is removed too

    def test_cleans_up_on_exception(self) -> None:
        saved: Path | None = None
        try:
            with spill_named(b"x", base_name="Book", suffix=".pdf") as path:
                saved = path
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        assert saved is not None
        assert not saved.exists()
