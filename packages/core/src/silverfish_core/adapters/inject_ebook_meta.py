"""Metadata injection via the native ``ebook-meta`` binary.

The inverse of :mod:`extract_ebook_meta`: it writes the book's *current* database
metadata back into the file on disk, so an e-reader (which reads metadata from
inside the file, not from our database) shows what the library shows.

Builds an argv (never a shell), so a title, author or any other metadata value
is passed verbatim and can never be interpreted as a command. ``ebook-meta``
rewrites the file in place for every format Calibre can write (EPUB, MOBI, AZW3,
PDF, ...).
"""

from pathlib import Path

from silverfish_core.adapters.calibre_binaries import ProcessRunner, SubprocessRunner
from silverfish_core.domain.models import Book


class EbookMetaInjector:
    """Embed a book's metadata into its file using ``ebook-meta``."""

    def __init__(self, *, ebook_meta: Path, runner: ProcessRunner | None = None) -> None:
        self._ebook_meta = ebook_meta
        self._runner: ProcessRunner = runner or SubprocessRunner()

    def inject(self, file_path: str, book: Book) -> None:
        argv = [str(self._ebook_meta), file_path, *self._metadata_args(book)]
        result = self._runner.run(argv)
        if result.returncode != 0:
            msg = self._clean_error(result.stderr)
            raise RuntimeError(msg)

    def _metadata_args(self, book: Book) -> list[str]:
        """Build the ``--set`` flags for the fields the book actually has.

        Title and authors are always written. Optional fields are only passed
        when present, so injecting never clears a field the file already holds
        with an empty value.
        """
        args: list[str] = ["--title", book.title]
        if book.authors:
            authors = " & ".join(a.name for a in book.authors)
            args += ["--authors", authors]
        if book.tags:
            args += ["--tags", ", ".join(t.name for t in book.tags)]
        if book.series is not None:
            args += ["--series", book.series.name, "--index", str(book.series_index)]
        if book.publisher:
            args += ["--publisher", book.publisher]
        if book.comment:
            args += ["--comments", book.comment]
        for language in book.languages:
            args += ["--language", language]
        for identifier in book.identifiers:
            args += ["--identifier", f"{identifier.scheme}:{identifier.value}"]
        return args

    def _clean_error(self, stderr: str) -> str:
        """Drop Python traceback noise, keeping the meaningful ebook-meta lines."""
        lines = [
            line
            for line in stderr.splitlines()
            if line.strip() and not line.startswith("Traceback") and not line.startswith("  File")
        ]
        return "\n".join(lines) if lines else "Writing metadata failed"
