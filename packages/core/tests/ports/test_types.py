"""Tests for the supporting types referenced by the ports.

Written before the implementation (TDD). These are neutral value objects that
form part of the port contracts: pagination, search filters, conversion result,
extracted metadata and external-source results.
"""

import pytest

from silverfish_core.ports.types import (
    BookMeta,
    ConversionResult,
    ExternalBook,
    Page,
    Quota,
    SearchFilters,
    SortDirection,
    SortField,
)


class TestPage:
    def test_computes_total_pages(self) -> None:
        page: Page[int] = Page(items=(1, 2, 3), total=25, page=1, page_size=10)
        assert page.total_pages == 3

    def test_total_pages_is_one_when_empty(self) -> None:
        page: Page[int] = Page(items=(), total=0, page=1, page_size=10)
        assert page.total_pages == 1

    def test_has_next_and_prev(self) -> None:
        middle: Page[int] = Page(items=(1,), total=25, page=2, page_size=10)
        assert middle.has_next is True
        assert middle.has_prev is True

    def test_first_page_has_no_prev(self) -> None:
        first: Page[int] = Page(items=(1,), total=25, page=1, page_size=10)
        assert first.has_prev is False

    def test_last_page_has_no_next(self) -> None:
        last: Page[int] = Page(items=(1,), total=25, page=3, page_size=10)
        assert last.has_next is False

    def test_is_frozen(self) -> None:
        import dataclasses

        page: Page[int] = Page(items=(1,), total=1, page=1, page_size=10)
        with pytest.raises(dataclasses.FrozenInstanceError):
            page.total = 99  # type: ignore[misc]

    def test_rejects_non_positive_page(self) -> None:
        with pytest.raises(ValueError, match="page"):
            Page(items=(), total=0, page=0, page_size=10)

    def test_rejects_non_positive_page_size(self) -> None:
        with pytest.raises(ValueError, match="page_size"):
            Page(items=(), total=0, page=1, page_size=0)


class TestSearchFilters:
    def test_defaults_are_empty(self) -> None:
        filters = SearchFilters()
        assert filters.include_tags == ()
        assert filters.exclude_tags == ()
        assert filters.languages == ()
        assert filters.formats == ()
        assert filters.rating_min is None
        assert filters.rating_max is None

    def test_carries_include_exclude(self) -> None:
        filters = SearchFilters(
            include_tags=("sci-fi",),
            exclude_tags=("romance",),
            languages=("eng",),
            rating_min=6,
        )
        assert filters.include_tags == ("sci-fi",)
        assert filters.exclude_tags == ("romance",)
        assert filters.rating_min == 6


class TestSortAndResults:
    def test_sort_enums_have_expected_members(self) -> None:
        assert SortField.TITLE.value == "title"
        assert SortField.AUTHOR.value == "author"
        assert SortDirection.ASC.value == "asc"
        assert SortDirection.DESC.value == "desc"

    def test_conversion_result_success(self) -> None:
        result = ConversionResult(ok=True, output_format="EPUB", error=None)
        assert result.ok is True
        assert result.error is None

    def test_conversion_result_failure_carries_error(self) -> None:
        result = ConversionResult(ok=False, output_format="MOBI", error="boom")
        assert result.ok is False
        assert result.error == "boom"


class TestExternalTypes:
    def test_book_meta_holds_extracted_fields(self) -> None:
        meta = BookMeta(title="1984", authors=("George Orwell",), extension=".epub")
        assert meta.title == "1984"
        assert meta.authors == ("George Orwell",)
        assert meta.cover is None

    def test_external_book_and_quota(self) -> None:
        book = ExternalBook(source="zlibrary", external_id="abc123", title="Dune")
        quota = Quota(remaining=7, limit=10)
        assert book.source == "zlibrary"
        assert quota.remaining == 7
        assert quota.limit == 10
