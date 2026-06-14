"""The import_book use case.

Given an uploaded file, extract its metadata, create the book record and place
the file (and cover) in storage at the Calibre-style path. Orchestrates the
ports: extractor + repository + storage. The only I/O it does is spilling the
uploaded bytes to a temp file so the extractor (which reads a path) can parse
them; that temp file is always cleaned up.
"""

from dataclasses import dataclass
from pathlib import Path

from silverfish_core.domain.models import Author, Book, BookFormat, Identifier, Series, Tag
from silverfish_core.domain.rules import author_sort, build_path, valid_filename
from silverfish_core.ports.extractor import MetadataExtractor
from silverfish_core.ports.repository import MetadataRepository
from silverfish_core.ports.storage import FileStorage
from silverfish_core.ports.types import BookMeta
from silverfish_core.services.spill import spill_named

_UNKNOWN_AUTHOR = "Unknown"


@dataclass(frozen=True, slots=True)
class UploadedFile:
    """An uploaded book file: its original name and raw bytes."""

    filename: str
    data: bytes


class ImportBookService:
    """Create a library book from an uploaded file."""

    def __init__(
        self,
        *,
        extractor: MetadataExtractor,
        repository: MetadataRepository,
        storage: FileStorage,
    ) -> None:
        self._extractor = extractor
        self._repository = repository
        self._storage = storage

    def import_book(
        self,
        upload: UploadedFile,
        *,
        allowed_extensions: tuple[str, ...] | None = None,
    ) -> Book:
        extension = self._extension(upload.filename)
        if allowed_extensions is not None and extension.lstrip(".") not in {
            e.lower().lstrip(".") for e in allowed_extensions
        }:
            msg = f"File extension '{extension}' is not allowed"
            raise ValueError(msg)

        meta = self._extract(upload, extension)
        book = self._build_book(meta, size=len(upload.data))
        created = self._repository.create_book(book)

        author_name = created.authors[0].name if created.authors else _UNKNOWN_AUTHOR
        if created.id is None:  # the repository must assign an id on create
            msg = "Repository returned a book without an id"
            raise RuntimeError(msg)
        book_dir = build_path(author_name, created.title, book_id=created.id)
        file_name = self._file_name(created.title, author_name, extension)
        self._storage.write_book_file(f"{book_dir}/{file_name}", upload.data)
        if meta.cover is not None:
            self._storage.write_cover(book_dir, meta.cover)

        return created

    def _extract(self, upload: UploadedFile, extension: str) -> BookMeta:
        """Spill the upload to a temp file (named after the original upload) so
        the path-based extractor reads a real name, never a temp name.
        """
        original_stem = Path(upload.filename).stem
        with spill_named(upload.data, base_name=original_stem, suffix=extension) as tmp_path:
            return self._extractor.extract(str(tmp_path), extension, fallback_title=original_stem)

    def _build_book(self, meta: BookMeta, *, size: int) -> Book:
        authors = tuple(Author(name=name, sort=author_sort(name)) for name in meta.authors)
        file_base = self._file_base(meta.title, authors[0].name if authors else _UNKNOWN_AUTHOR)
        return Book(
            id=None,
            title=meta.title,
            sort="",  # repository computes via Calibre's title_sort
            author_sort="",  # repository computes
            authors=authors,
            tags=tuple(Tag(name=t) for t in meta.tags),
            series=Series(name=meta.series, sort=meta.series) if meta.series else None,
            series_index=meta.series_index if meta.series_index is not None else 1.0,
            languages=meta.languages,
            publisher=meta.publisher,
            identifiers=tuple(Identifier(scheme=s, value=v) for s, v in meta.identifiers),
            formats=(
                BookFormat(
                    extension=meta.extension.lstrip(".").upper(),
                    size_bytes=size,
                    name=file_base,
                ),
            ),
            comment=meta.description,
            has_cover=meta.cover is not None,
        )

    def _extension(self, filename: str) -> str:
        _, dot, ext = filename.rpartition(".")
        return f".{ext.lower()}" if dot else ""

    def _file_base(self, title: str, author: str) -> str:
        # Matches Calibre's "Title - Author" data file name (not the directory).
        return f"{valid_filename(title, chars=42)} - {valid_filename(author, chars=42)}"

    def _file_name(self, title: str, author: str, extension: str) -> str:
        return f"{self._file_base(title, author)}{extension}"
