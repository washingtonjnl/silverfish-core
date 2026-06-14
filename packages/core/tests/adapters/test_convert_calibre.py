"""Tests for the ebook-convert adapter.

Written before the implementation (TDD). The adapter shells out to ebook-convert
via the safe runner, parsing its percentage output into progress. Unit behaviour
is covered with a fake runner; a real end-to-end conversion runs only when the
binary is installed (skipped otherwise so CI without Calibre still passes).
"""

from pathlib import Path

import pytest

from silverfish_core.adapters.calibre_binaries import CalibreBinaries, ProcessResult
from silverfish_core.adapters.convert_calibre import CalibreConverter
from silverfish_core.ports import Converter

EBOOKS = Path(__file__).parent.parent / "fixtures" / "ebooks"
_BINARIES = CalibreBinaries()
_HAS_CONVERT = _BINARIES.ebook_convert is not None


class FakeRunner:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self._result = ProcessResult(returncode=returncode, stdout=stdout, stderr=stderr)

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = 600.0,
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        self.calls.append(argv)
        return self._result


def _converter(
    runner: FakeRunner, *, convert_path: str = "/fake/ebook-convert"
) -> CalibreConverter:
    return CalibreConverter(ebook_convert=Path(convert_path), runner=runner)


class TestConformance:
    def test_is_a_converter(self) -> None:
        assert isinstance(_converter(FakeRunner()), Converter)


class TestCommand:
    def test_invokes_ebook_convert_with_in_and_out(self) -> None:
        runner = FakeRunner(stdout="100% done")
        result = _converter(runner).convert("in.epub", "out.pdf")
        assert result.ok is True
        assert runner.calls == [["/fake/ebook-convert", "in.epub", "out.pdf"]]

    def test_passes_cover_and_opf_when_given(self) -> None:
        runner = FakeRunner(stdout="100%")
        _converter(runner).convert("in.epub", "out.mobi", opf=b"<opf/>", cover=b"\xff\xd8")
        argv = runner.calls[0]
        assert "--from-opf" in argv
        assert "--cover" in argv

    def test_output_format_is_reported(self) -> None:
        result = _converter(FakeRunner(stdout="100%")).convert("in.epub", "out.azw3")
        assert result.output_format == "AZW3"


class TestProgressAndErrors:
    def test_progress_callback_receives_percentages(self) -> None:
        runner = FakeRunner(stdout="10% Parsing\n55% Converting\n100% Done")
        seen: list[float] = []
        _converter(runner).convert("in.epub", "out.pdf", on_progress=seen.append)
        assert 0.1 in seen
        assert 1.0 in seen

    def test_nonzero_return_is_failure(self) -> None:
        runner = FakeRunner(returncode=1, stderr="Calibre failed with error: boom")
        result = _converter(runner).convert("in.epub", "out.pdf")
        assert result.ok is False
        assert result.error is not None
        assert "boom" in result.error

    def test_traceback_lines_filtered_from_error(self) -> None:
        runner = FakeRunner(
            returncode=1,
            stderr="Traceback (most recent call last):\n  File x\nValueError: real cause",
        )
        result = _converter(runner).convert("in.epub", "out.pdf")
        assert result.error is not None
        assert "Traceback" not in result.error
        assert "real cause" in result.error


@pytest.mark.skipif(not _HAS_CONVERT, reason="ebook-convert not installed")
class TestRealConversion:
    def test_converts_epub_to_pdf(self, tmp_path: Path) -> None:
        assert _BINARIES.ebook_convert is not None
        converter = CalibreConverter(ebook_convert=_BINARIES.ebook_convert)
        out = tmp_path / "out.pdf"
        # minimal.epub has no embedded cover (the fake cover in rich.epub is not a
        # real JPEG and trips ebook-convert's PDF renderer).
        result = converter.convert(str(EBOOKS / "minimal.epub"), str(out))
        assert result.ok is True
        assert out.exists()
        assert out.stat().st_size > 0
