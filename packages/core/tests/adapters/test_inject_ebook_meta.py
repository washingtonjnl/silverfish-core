"""Tests for the ebook-meta metadata injector.

Written before the implementation (TDD). The injector embeds a book's current
database metadata back into the file on disk by invoking ``ebook-meta`` with the
``--set`` style flags. Filenames and metadata values are always passed as argv
elements (never a shell), so they cannot be interpreted as commands. Unit
behaviour is covered with a fake runner; a real round-trip runs only when the
binary is installed (skipped otherwise so CI without Calibre still passes).
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from silverfish_core.adapters.calibre_binaries import CalibreBinaries, ProcessResult
from silverfish_core.adapters.inject_ebook_meta import EbookMetaInjector
from silverfish_core.domain.models import Author, Book, Identifier, Series, Tag
from silverfish_core.ports import MetadataInjector

_BINARIES = CalibreBinaries()
_HAS_META = _BINARIES.ebook_meta is not None


class FakeRunner:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self._result = ProcessResult(returncode=returncode, stdout=stdout, stderr=stderr)

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = 600.0,
        env: dict[str, str] | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> ProcessResult:
        self.calls.append(argv)
        return self._result


def _injector(runner: FakeRunner, *, meta_path: str = "/fake/ebook-meta") -> EbookMetaInjector:
    return EbookMetaInjector(ebook_meta=Path(meta_path), runner=runner)


def _book(**overrides: object) -> Book:
    base: dict[str, object] = {
        "id": 1,
        "title": "The Great Book",
        "sort": "Great Book, The",
        "author_sort": "Austen, Jane",
        "authors": (Author(name="Jane Austen", sort="Austen, Jane"),),
        "tags": (Tag(name="Classic"), Tag(name="Romance")),
        "series": Series(name="My Series", sort="My Series"),
        "series_index": 2.0,
        "publisher": "Penguin",
        "languages": ("eng",),
        "comment": "A description.",
        "identifiers": (Identifier(scheme="isbn", value="123"),),
    }
    base.update(overrides)
    return Book(**base)  # type: ignore[arg-type]


class TestConformance:
    def test_is_a_metadata_injector(self) -> None:
        assert isinstance(_injector(FakeRunner()), MetadataInjector)


class TestCommand:
    def test_invokes_ebook_meta_on_the_file(self) -> None:
        runner = FakeRunner()
        _injector(runner).inject("/lib/book.epub", _book())
        assert len(runner.calls) == 1
        argv = runner.calls[0]
        assert argv[0] == "/fake/ebook-meta"
        assert argv[1] == "/lib/book.epub"

    def test_sets_scalar_fields(self) -> None:
        runner = FakeRunner()
        _injector(runner).inject("/lib/book.epub", _book())
        argv = runner.calls[0]
        assert "--title" in argv
        assert argv[argv.index("--title") + 1] == "The Great Book"
        assert "--publisher" in argv
        assert argv[argv.index("--publisher") + 1] == "Penguin"
        assert "--comments" in argv
        assert argv[argv.index("--comments") + 1] == "A description."

    def test_authors_are_ampersand_joined(self) -> None:
        runner = FakeRunner()
        book = _book(
            authors=(
                Author(name="Jane Austen", sort="Austen, Jane"),
                Author(name="John Doe", sort="Doe, John"),
            )
        )
        _injector(runner).inject("/lib/book.epub", book)
        argv = runner.calls[0]
        assert argv[argv.index("--authors") + 1] == "Jane Austen & John Doe"

    def test_tags_are_comma_joined(self) -> None:
        runner = FakeRunner()
        _injector(runner).inject("/lib/book.epub", _book())
        argv = runner.calls[0]
        assert argv[argv.index("--tags") + 1] == "Classic, Romance"

    def test_series_and_index_are_set(self) -> None:
        runner = FakeRunner()
        _injector(runner).inject("/lib/book.epub", _book())
        argv = runner.calls[0]
        assert argv[argv.index("--series") + 1] == "My Series"
        assert argv[argv.index("--index") + 1] == "2.0"

    def test_languages_are_set(self) -> None:
        runner = FakeRunner()
        _injector(runner).inject("/lib/book.epub", _book())
        argv = runner.calls[0]
        assert argv[argv.index("--language") + 1] == "eng"

    def test_identifiers_are_set_scheme_colon_value(self) -> None:
        runner = FakeRunner()
        _injector(runner).inject("/lib/book.epub", _book())
        argv = runner.calls[0]
        assert argv[argv.index("--identifier") + 1] == "isbn:123"


class TestOmittedFields:
    def test_absent_optional_fields_are_not_passed(self) -> None:
        runner = FakeRunner()
        book = _book(
            series=None,
            publisher=None,
            comment=None,
            tags=(),
            languages=(),
            identifiers=(),
        )
        _injector(runner).inject("/lib/book.epub", book)
        argv = runner.calls[0]
        assert "--series" not in argv
        assert "--index" not in argv
        assert "--publisher" not in argv
        assert "--comments" not in argv
        assert "--tags" not in argv
        assert "--language" not in argv
        assert "--identifier" not in argv
        # Title and authors are always present.
        assert "--title" in argv
        assert "--authors" in argv


class TestErrors:
    def test_nonzero_exit_raises_with_clean_message(self) -> None:
        runner = FakeRunner(returncode=1, stderr="ebook-meta: could not write metadata")
        with pytest.raises(RuntimeError, match="could not write metadata"):
            _injector(runner).inject("/lib/book.epub", _book())


@pytest.mark.skipif(not _HAS_META, reason="ebook-meta not installed")
class TestRealBinary:
    def test_round_trip_sets_title_in_real_epub(self, tmp_path: Path) -> None:
        src = Path(__file__).parent.parent / "fixtures" / "ebooks"
        epubs = list(src.glob("*.epub"))
        if not epubs:
            pytest.skip("no epub fixture available")
        target = tmp_path / "book.epub"
        target.write_bytes(epubs[0].read_bytes())

        injector = EbookMetaInjector(ebook_meta=_BINARIES.ebook_meta)  # type: ignore[arg-type]
        book = _book(title="A Brand New Title", authors=(Author(name="Tester", sort="Tester"),))
        injector.inject(str(target), book)

        extractor_argv = [str(_BINARIES.ebook_meta), str(target)]
        from silverfish_core.adapters.calibre_binaries import SubprocessRunner

        out = SubprocessRunner().run(extractor_argv)
        assert "A Brand New Title" in out.stdout
