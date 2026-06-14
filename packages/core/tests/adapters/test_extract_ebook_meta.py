"""Tests for the ebook-meta metadata extractor.

Written before the implementation (TDD). The adapter runs ebook-meta to dump
metadata to an OPF (and the cover to a file), then parses them. Unit behaviour
uses a fake runner that writes a known OPF; a real extraction runs only when the
binary is installed.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from silverfish_core.adapters.calibre_binaries import CalibreBinaries, ProcessResult
from silverfish_core.adapters.extract_ebook_meta import EbookMetaExtractor
from silverfish_core.ports import MetadataExtractor

EBOOKS = Path(__file__).parent.parent / "fixtures" / "ebooks"
_META = CalibreBinaries().ebook_meta
_HAS_META = _META is not None

_OPF = """<?xml version='1.0' encoding='utf-8'?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"
            xmlns:opf="http://www.idpf.org/2007/opf">
    <dc:title>Real PDF Title</dc:title>
    <dc:creator opf:role="aut">Ada Lovelace</dc:creator>
    <dc:language>eng</dc:language>
    <dc:subject>science</dc:subject>
    <meta name="calibre:series" content="Analytical" />
    <meta name="calibre:series_index" content="2" />
  </metadata>
</package>
"""


class FakeRunner:
    """Writes a fixed OPF to the --to-opf path and a cover to --get-cover."""

    def __init__(self, *, opf: str = _OPF, cover: bytes | None = b"\xff\xd8COVER") -> None:
        self._opf = opf
        self._cover = cover
        self.calls: list[list[str]] = []

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = 600.0,
        env: dict[str, str] | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> ProcessResult:
        self.calls.append(argv)
        if "--to-opf" in argv:
            Path(argv[argv.index("--to-opf") + 1]).write_text(self._opf, encoding="utf-8")
        if "--get-cover" in argv and self._cover is not None:
            Path(argv[argv.index("--get-cover") + 1]).write_bytes(self._cover)
        return ProcessResult(returncode=0, stdout="", stderr="")


def _extractor(runner: FakeRunner) -> EbookMetaExtractor:
    return EbookMetaExtractor(ebook_meta=Path("/fake/ebook-meta"), runner=runner)


class TestConformance:
    def test_is_a_metadata_extractor(self) -> None:
        assert isinstance(_extractor(FakeRunner()), MetadataExtractor)


class TestExtraction:
    def test_extracts_title_author_from_opf(self) -> None:
        meta = _extractor(FakeRunner()).extract("/x/book.pdf", ".pdf")
        assert meta.title == "Real PDF Title"
        assert meta.authors == ("Ada Lovelace",)
        assert meta.extension == ".pdf"

    def test_extracts_series_and_tags(self) -> None:
        meta = _extractor(FakeRunner()).extract("/x/book.pdf", ".pdf")
        assert meta.series == "Analytical"
        assert meta.series_index == 2.0
        assert "science" in meta.tags

    def test_extracts_cover(self) -> None:
        meta = _extractor(FakeRunner()).extract("/x/book.pdf", ".pdf")
        assert meta.cover == b"\xff\xd8COVER"

    def test_no_cover_when_not_produced(self) -> None:
        meta = _extractor(FakeRunner(cover=None)).extract("/x/book.pdf", ".pdf")
        assert meta.cover is None

    def test_falls_back_on_nonzero_return(self) -> None:
        class FailingRunner:
            def run(
                self,
                argv: list[str],
                *,
                timeout: float = 600.0,
                env: dict[str, str] | None = None,
                on_line: Callable[[str], None] | None = None,
            ) -> ProcessResult:
                return ProcessResult(returncode=1, stdout="", stderr="boom")

        meta = EbookMetaExtractor(
            ebook_meta=Path("/fake/ebook-meta"), runner=FailingRunner()
        ).extract("/x/My Book.pdf", ".pdf", fallback_title="My Book")
        assert meta.title == "My Book"


@pytest.mark.skipif(not _HAS_META, reason="ebook-meta not installed")
class TestRealExtraction:
    def test_reads_epub_metadata(self) -> None:
        assert _META is not None
        meta = EbookMetaExtractor(ebook_meta=_META).extract(str(EBOOKS / "rich.epub"), ".epub")
        assert meta.title == "The Hobbit"
        assert "J. R. R. Tolkien" in meta.authors
