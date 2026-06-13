"""Tests for the pure-Python metadata extractor (EPUB).

Written before the implementation (TDD). Extraction reads the OPF inside the
EPUB ZIP — no Calibre binary involved. Fixtures live in tests/fixtures/ebooks:

- rich.epub:    full metadata (authors, language, tags, series, publisher,
                identifiers) and an embedded cover.
- minimal.epub: title + one author, no cover.
"""

from pathlib import Path

import pytest

from silverfish_core.adapters.extract_python import PythonMetadataExtractor
from silverfish_core.ports import MetadataExtractor
from silverfish_core.ports.types import BookMeta

EBOOKS = Path(__file__).parent.parent / "fixtures" / "ebooks"


@pytest.fixture
def extractor() -> PythonMetadataExtractor:
    return PythonMetadataExtractor()


class TestConformance:
    def test_is_a_metadata_extractor(self, extractor: PythonMetadataExtractor) -> None:
        assert isinstance(extractor, MetadataExtractor)


class TestEpubExtraction:
    def test_returns_book_meta(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "rich.epub"), ".epub")
        assert isinstance(meta, BookMeta)

    def test_extracts_title_and_authors(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "rich.epub"), ".epub")
        assert meta.title == "The Hobbit"
        assert meta.authors == ("J. R. R. Tolkien",)

    def test_extracts_language(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "rich.epub"), ".epub")
        assert meta.languages == ("en",)

    def test_extracts_tags(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "rich.epub"), ".epub")
        assert set(meta.tags) == {"fantasy", "adventure"}

    def test_extracts_series_and_index(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "rich.epub"), ".epub")
        assert meta.series == "Middle-earth"
        assert meta.series_index == 1.0

    def test_extracts_publisher(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "rich.epub"), ".epub")
        assert meta.publisher == "Allen & Unwin"

    def test_extracts_identifiers(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "rich.epub"), ".epub")
        idents = dict(meta.identifiers)
        assert idents["isbn"] == "9780261103344"
        assert idents["google"] == "abc123"

    def test_extracts_cover_bytes(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "rich.epub"), ".epub")
        assert meta.cover is not None
        assert meta.cover.startswith(b"\xff\xd8")  # JPEG SOI marker

    def test_extension_is_recorded(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "rich.epub"), ".epub")
        assert meta.extension == ".epub"


class TestMinimalEpub:
    def test_minimal_has_title_author_no_cover(self, extractor: PythonMetadataExtractor) -> None:
        meta = extractor.extract(str(EBOOKS / "minimal.epub"), ".epub")
        assert meta.title == "Untitled Notes"
        assert meta.authors == ("Anonymous",)
        assert meta.cover is None
        assert meta.tags == ()
        assert meta.series is None


class TestFallbackTitle:
    def test_fallback_prefers_original_name_over_temp_path(
        self, extractor: PythonMetadataExtractor, tmp_path: Path
    ) -> None:
        # Simulates the upload flow: bytes are in a temp file, but the title must
        # come from the original upload name, not the temp stem.
        temp = tmp_path / "tmpssimkxey"
        temp.write_bytes(b"not a real book")
        meta = extractor.extract(str(temp), ".xyz", fallback_title="Real Book Name")
        assert meta.title == "Real Book Name"

    def test_fallback_uses_stem_when_no_original_given(
        self, extractor: PythonMetadataExtractor, tmp_path: Path
    ) -> None:
        f = tmp_path / "My Book.txt"
        f.write_bytes(b"plain text")
        meta = extractor.extract(str(f), ".txt")
        assert meta.title == "My Book"
        assert meta.extension == ".txt"


class TestUnsupportedAndErrors:
    def test_unknown_extension_falls_back_to_filename_title(
        self, extractor: PythonMetadataExtractor, tmp_path: Path
    ) -> None:
        f = tmp_path / "My Book.txt"
        f.write_bytes(b"plain text")
        meta = extractor.extract(str(f), ".txt")
        # No parser for .txt: title defaults to the filename stem.
        assert meta.title == "My Book"
        assert meta.extension == ".txt"

    def test_corrupt_epub_falls_back_gracefully(
        self, extractor: PythonMetadataExtractor, tmp_path: Path
    ) -> None:
        bad = tmp_path / "broken.epub"
        bad.write_bytes(b"not a zip")
        meta = extractor.extract(str(bad), ".epub")
        # Must not raise; falls back to filename-derived title.
        assert meta.title == "broken"

    def test_corrupt_pdf_falls_back_gracefully(
        self, extractor: PythonMetadataExtractor, tmp_path: Path
    ) -> None:
        bad = tmp_path / "broken.pdf"
        bad.write_bytes(b"not a pdf")
        meta = extractor.extract(str(bad), ".pdf", fallback_title="broken")
        assert meta.title == "broken"
        assert meta.cover is None
