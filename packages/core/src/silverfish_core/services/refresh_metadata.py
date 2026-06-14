"""The refresh_metadata use case.

Re-extracts metadata from one of a book's format files and patches the record:
fields the extraction produced replace the current ones; fields it could not
produce keep their existing values, so refreshing from a sparse file never
erases good metadata.
"""

import dataclasses
from pathlib import Path

from silverfish_core.domain.models import Author, Book, Series, Tag
from silverfish_core.ports.extractor import MetadataExtractor
from silverfish_core.ports.repository import MetadataRepository
from silverfish_core.ports.storage import FileStorage
from silverfish_core.ports.types import BookMeta
from silverfish_core.services.edit_book import BookEditor
from silverfish_core.services.spill import spill_named


class RefreshMetadataService:
    """Refresh a book's metadata from one of its format files."""

    def __init__(
        self,
        *,
        repository: MetadataRepository,
        storage: FileStorage,
        extractor: MetadataExtractor,
        edit_service: BookEditor,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._extractor = extractor
        self._edit_service = edit_service

    def refresh(self, *, book_id: int, source_format: str) -> Book:
        current = self._repository.get_book(book_id)
        if current is None:
            msg = f"Book {book_id} not found"
            raise ValueError(msg)

        source_rel = self._repository.format_path(book_id, source_format)
        if source_rel is None:
            msg = f"Book {book_id} has no format {source_format!r} to refresh from"
            raise ValueError(msg)

        meta = self._extract(source_rel, fallback_title=current.title)
        merged = self._merge(current, meta)
        return self._edit_service.edit_book(merged)

    def _extract(self, source_rel: str, *, fallback_title: str) -> BookMeta:
        data = self._storage.read_book_file(source_rel)
        suffix = Path(source_rel).suffix
        # Name the temp after the book's current title, so a tool that falls back
        # to the filename gets a real name rather than a temp name.
        with spill_named(data, base_name=fallback_title, suffix=suffix) as tmp_path:
            return self._extractor.extract(str(tmp_path), suffix, fallback_title=fallback_title)

    def _merge(self, book: Book, meta: BookMeta) -> Book:
        """Replace fields the extraction produced; keep existing ones otherwise."""
        changes: dict[str, object] = {}
        if meta.title.strip():
            changes["title"] = meta.title
        if meta.authors:
            changes["authors"] = tuple(Author(name=n, sort="") for n in meta.authors)
            changes["author_sort"] = ""  # repository recomputes
        if meta.tags:
            changes["tags"] = tuple(Tag(name=t) for t in meta.tags)
        if meta.series:
            changes["series"] = Series(name=meta.series, sort=meta.series)
            if meta.series_index is not None:
                changes["series_index"] = meta.series_index
        if meta.languages:
            changes["languages"] = meta.languages
        if meta.publisher:
            changes["publisher"] = meta.publisher
        if meta.description:
            changes["comment"] = meta.description
        return dataclasses.replace(book, **changes)  # type: ignore[arg-type]  # validated field names
