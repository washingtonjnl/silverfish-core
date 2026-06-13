"""Tests for the neutral domain models.

Written before the implementation (TDD). These models are storage-agnostic:
they intentionally do not carry Calibre quirks (e.g. rating is a plain 0-10
integer here; the SQLite-Calibre adapter is responsible for the on-disk x2
representation). They are the vocabulary every service and adapter speaks.
"""

import dataclasses
from datetime import UTC, datetime

import pytest

from silverfish_core.domain.models import (
    Author,
    Book,
    BookFormat,
    Identifier,
    Series,
    Tag,
)


class TestValueObjects:
    def test_author_holds_name_and_sort(self) -> None:
        author = Author(name="George Orwell", sort="Orwell, George")
        assert author.name == "George Orwell"
        assert author.sort == "Orwell, George"

    def test_value_objects_are_frozen(self) -> None:
        tag = Tag(name="sci-fi")
        with pytest.raises(dataclasses.FrozenInstanceError):
            tag.name = "fantasy"  # type: ignore[misc]

    def test_identifier_holds_type_and_value(self) -> None:
        ident = Identifier(scheme="isbn", value="9780451524935")
        assert ident.scheme == "isbn"
        assert ident.value == "9780451524935"

    def test_series_holds_name_and_sort(self) -> None:
        series = Series(name="The Lord of the Rings", sort="Lord of the Rings, The")
        assert series.name == "The Lord of the Rings"

    def test_book_format_holds_extension_and_size(self) -> None:
        fmt = BookFormat(extension="EPUB", size_bytes=1024, name="1984 - George Orwell")
        assert fmt.extension == "EPUB"
        assert fmt.size_bytes == 1024


class TestBook:
    def _minimal_book(self) -> Book:
        return Book(
            id=None,
            title="1984",
            sort="1984",
            author_sort="Orwell, George",
            authors=(Author(name="George Orwell", sort="Orwell, George"),),
        )

    def test_minimal_book_has_sensible_defaults(self) -> None:
        book = self._minimal_book()
        assert book.id is None
        assert book.title == "1984"
        assert book.tags == ()
        assert book.series is None
        assert book.series_index == 1.0
        assert book.rating is None
        assert book.identifiers == ()
        assert book.formats == ()
        assert book.languages == ()
        assert book.has_cover is False

    def test_book_is_frozen(self) -> None:
        book = self._minimal_book()
        with pytest.raises(dataclasses.FrozenInstanceError):
            book.title = "Animal Farm"  # type: ignore[misc]

    def test_book_carries_rich_metadata(self) -> None:
        book = Book(
            id=42,
            title="The Hobbit",
            sort="Hobbit, The",
            author_sort="Tolkien, J. R. R.",
            authors=(Author(name="J. R. R. Tolkien", sort="Tolkien, J. R. R."),),
            tags=(Tag(name="fantasy"),),
            series=Series(name="Middle-earth", sort="Middle-earth"),
            series_index=1.0,
            rating=9,
            languages=("eng",),
            identifiers=(Identifier(scheme="isbn", value="9780261103344"),),
            formats=(BookFormat(extension="EPUB", size_bytes=2048, name="The Hobbit"),),
            has_cover=True,
            pubdate=datetime(1937, 9, 21, tzinfo=UTC),
        )
        assert book.rating == 9
        assert book.tags[0].name == "fantasy"
        assert book.series is not None
        assert book.series.name == "Middle-earth"
        assert book.languages == ("eng",)

    def test_rating_is_domain_scale_zero_to_ten(self) -> None:
        # Neutral domain uses a 0-10 integer; no Calibre x2 leakage here.
        book = dataclasses.replace(self._minimal_book(), rating=10)
        assert book.rating == 10
