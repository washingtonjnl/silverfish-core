"""Composite metadata extractor: native EPUB + ebook-meta for everything else.

EPUB/KEPUB are parsed in pure Python (no binary needed, so EPUB upload never
depends on Calibre). Every other format is delegated to the ebook-meta extractor
when it is available; if it is not, extraction degrades to a filename-derived
title via the native extractor's own fallback.
"""

from pathlib import Path

from silverfish_core.ports.extractor import MetadataExtractor
from silverfish_core.ports.types import BookMeta

_NATIVE_EXTENSIONS = {".epub", ".kepub"}


class CompositeMetadataExtractor:
    """Route each format to the extractor that handles it best."""

    def __init__(
        self,
        *,
        native: MetadataExtractor,
        ebook_meta: MetadataExtractor | None,
    ) -> None:
        self._native = native
        self._ebook_meta = ebook_meta

    def extract(
        self, file_path: str, extension: str, *, fallback_title: str | None = None
    ) -> BookMeta:
        ext = extension.lower() or Path(file_path).suffix.lower()
        if ext in _NATIVE_EXTENSIONS or self._ebook_meta is None:
            return self._native.extract(file_path, extension, fallback_title=fallback_title)
        return self._ebook_meta.extract(file_path, extension, fallback_title=fallback_title)
