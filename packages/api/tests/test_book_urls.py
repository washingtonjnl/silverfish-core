"""Tests for the convenience URLs on BookOut (cover_url, per-format download_url).

Written before the implementation (TDD). The API gives clients ready-to-use
URLs so they never construct paths themselves: a cover_url when the book has a
cover, and a download_url on each format pointing at that specific file.
"""

from datetime import UTC, datetime

from silverfish_api.schemas import BookOut
from silverfish_core.domain.models import Author, Book, BookFormat


def _book(*, book_id: int = 42, has_cover: bool = True) -> Book:
    return Book(
        id=book_id,
        title="The Hobbit",
        sort="Hobbit, The",
        author_sort="Tolkien, J. R. R.",
        authors=(Author(name="J. R. R. Tolkien", sort="Tolkien, J. R. R."),),
        formats=(
            BookFormat(extension="EPUB", size_bytes=10, name="The Hobbit - J. R. R. Tolkien"),
            BookFormat(extension="PDF", size_bytes=20, name="The Hobbit - J. R. R. Tolkien"),
        ),
        has_cover=has_cover,
        pubdate=datetime(1937, 9, 21, tzinfo=UTC),
    )


class TestPublicId:
    def test_id_is_base62_of_internal_id(self) -> None:
        # 42 -> "g" in base62 (0-9, A-Z, a-z; 42 = 36 + 6).
        out = BookOut.from_domain(_book(book_id=42))
        assert out.id == "g"

    def test_small_id_stays_numeric_string(self) -> None:
        # 7 -> "7": the public id is always a string, even when it looks numeric.
        out = BookOut.from_domain(_book(book_id=7))
        assert out.id == "7"


class TestCoverUrl:
    def test_cover_url_present_when_has_cover(self) -> None:
        out = BookOut.from_domain(_book(has_cover=True))
        # URL uses the public base62 id (42 -> "g").
        assert out.cover_url == "/books/g/cover"

    def test_cover_url_none_when_no_cover(self) -> None:
        out = BookOut.from_domain(_book(has_cover=False))
        assert out.cover_url is None


class TestFormatDownloadUrl:
    def test_each_format_has_its_own_download_url(self) -> None:
        out = BookOut.from_domain(_book(book_id=7))
        by_ext = {f.extension: f.download_url for f in out.formats}
        assert by_ext["EPUB"] == "/books/7/formats/epub"
        assert by_ext["PDF"] == "/books/7/formats/pdf"

    def test_download_url_uses_lowercase_extension(self) -> None:
        out = BookOut.from_domain(_book(book_id=7))
        assert all(f.download_url == f.download_url.lower() for f in out.formats)
