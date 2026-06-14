"""Tests for the composite metadata extractor.

Written before the implementation (TDD). EPUB goes through the native Python
extractor (no binary); every other format goes through ebook-meta when
available, and otherwise falls back to a filename-derived title.
"""

from silverfish_core.adapters.extract_composite import CompositeMetadataExtractor
from silverfish_core.ports import MetadataExtractor
from silverfish_core.ports.types import BookMeta


class RecordingExtractor:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls: list[tuple[str, str]] = []

    def extract(
        self, file_path: str, extension: str, *, fallback_title: str | None = None
    ) -> BookMeta:
        self.calls.append((file_path, extension))
        return BookMeta(title=f"{self.name}:{fallback_title or 'x'}", extension=extension)


def _composite(
    *, with_meta: bool = True
) -> tuple[CompositeMetadataExtractor, RecordingExtractor, RecordingExtractor | None]:
    native = RecordingExtractor("native")
    meta = RecordingExtractor("meta") if with_meta else None
    return CompositeMetadataExtractor(native=native, ebook_meta=meta), native, meta


class TestRouting:
    def test_is_a_metadata_extractor(self) -> None:
        composite, _, _ = _composite()
        assert isinstance(composite, MetadataExtractor)

    def test_epub_uses_native(self) -> None:
        composite, native, meta = _composite()
        composite.extract("/x/book.epub", ".epub")
        assert native.calls == [("/x/book.epub", ".epub")]
        assert meta is not None
        assert meta.calls == []

    def test_kepub_uses_native(self) -> None:
        composite, native, _ = _composite()
        composite.extract("/x/book.kepub", ".kepub")
        assert native.calls == [("/x/book.kepub", ".kepub")]

    def test_pdf_uses_ebook_meta(self) -> None:
        composite, native, meta = _composite()
        composite.extract("/x/book.pdf", ".pdf")
        assert native.calls == []
        assert meta is not None
        assert meta.calls == [("/x/book.pdf", ".pdf")]

    def test_mobi_uses_ebook_meta(self) -> None:
        composite, _, meta = _composite()
        composite.extract("/x/book.mobi", ".mobi")
        assert meta is not None
        assert meta.calls == [("/x/book.mobi", ".mobi")]


class TestDegradation:
    def test_non_epub_routes_to_native_when_no_ebook_meta(self) -> None:
        # ebook-meta unavailable: non-EPUB is handled by the native extractor
        # (whose own fallback derives a title from the filename).
        composite, native, _ = _composite(with_meta=False)
        meta = composite.extract("/x/My Doc.pdf", ".pdf", fallback_title="My Doc")
        assert native.calls == [("/x/My Doc.pdf", ".pdf")]
        assert meta.extension == ".pdf"

    def test_epub_still_native_without_ebook_meta(self) -> None:
        composite, native, _ = _composite(with_meta=False)
        composite.extract("/x/book.epub", ".epub")
        assert native.calls == [("/x/book.epub", ".epub")]
