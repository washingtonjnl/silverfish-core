"""Metadata extraction via the native ``ebook-meta`` binary.

Works for any format Calibre can read (PDF, MOBI, AZW3, ...). It dumps metadata
to a temp OPF (parsed with the shared OPF parser) and the cover to a temp file,
then cleans both up. On any failure it falls back to the original upload name as
title, so a bad file never breaks the upload.
"""

import tempfile
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml.ElementTree import fromstring as defused_fromstring

from silverfish_core.adapters._opf import parse_opf
from silverfish_core.adapters.calibre_binaries import ProcessRunner, SubprocessRunner
from silverfish_core.ports.types import BookMeta

_MAX_OPF_BYTES = 4 * 1024 * 1024


class EbookMetaExtractor:
    """Extract metadata (and cover) from a book file using ``ebook-meta``."""

    def __init__(self, *, ebook_meta: Path, runner: ProcessRunner | None = None) -> None:
        self._ebook_meta = ebook_meta
        self._runner: ProcessRunner = runner or SubprocessRunner()

    def extract(
        self, file_path: str, extension: str, *, fallback_title: str | None = None
    ) -> BookMeta:
        ext = extension.lower()
        title = (
            fallback_title.strip()
            if fallback_title and fallback_title.strip()
            else Path(file_path).stem
        )
        with (
            tempfile.NamedTemporaryFile(suffix=".opf", delete=False) as opf_tmp,
            tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as cover_tmp,
        ):
            opf_path = Path(opf_tmp.name)
            cover_path = Path(cover_tmp.name)

        try:
            result = self._runner.run(
                [
                    str(self._ebook_meta),
                    file_path,
                    "--to-opf",
                    str(opf_path),
                    "--get-cover",
                    str(cover_path),
                ]
            )
            if result.returncode != 0 or not opf_path.exists():
                return BookMeta(title=title, extension=ext)

            opf_bytes = opf_path.read_bytes()
            if len(opf_bytes) > _MAX_OPF_BYTES:
                return BookMeta(title=title, extension=ext)
            try:
                root = defused_fromstring(opf_bytes)
            except ParseError:
                return BookMeta(title=title, extension=ext)

            cover = self._read_cover(cover_path)
            return parse_opf(root, extension=ext, fallback_title=title, cover=cover)
        finally:
            opf_path.unlink(missing_ok=True)
            cover_path.unlink(missing_ok=True)

    def _read_cover(self, cover_path: Path) -> bytes | None:
        if not cover_path.exists():
            return None
        data = cover_path.read_bytes()
        return data or None
