"""Conformance tests for the port protocols.

Written before the implementation (TDD). Protocols have no behaviour, so these
tests assert the contracts are coherent and implementable: a minimal fake for
each port conforms both structurally (a typed variable of the protocol type
accepts it — checked by mypy) and at runtime (``isinstance`` against the
runtime-checkable protocol).
"""

from collections.abc import Callable
from datetime import datetime
from email.message import EmailMessage

from silverfish_core.domain.models import Book
from silverfish_core.ports import (
    Converter,
    DataSource,
    FileStorage,
    Mailer,
    MetadataExtractor,
    MetadataInjector,
    MetadataRepository,
)
from silverfish_core.ports.types import (
    BookMeta,
    ConversionResult,
    ExternalBook,
    Page,
    Quota,
    SearchFilters,
    SortOrder,
)


class FakeRepository:
    def get_book(self, book_id: int) -> Book | None:
        return None

    def list_books(self, *, page: int, page_size: int, sort: SortOrder) -> Page[Book]:
        return Page(items=(), total=0, page=page, page_size=page_size)

    def search(self, term: str, *, filters: SearchFilters, page: int, page_size: int) -> Page[Book]:
        return Page(items=(), total=0, page=page, page_size=page_size)

    def create_book(self, book: Book) -> Book:
        return book

    def update_book(self, book: Book) -> Book:
        return book

    def delete_book(self, book_id: int) -> None:
        return None

    def cover_path(self, book_id: int) -> str | None:
        return None

    def format_path(self, book_id: int, book_format: str) -> str | None:
        return None


class FakeStorage:
    def read_book_file(self, path: str) -> bytes:
        return b""

    def write_book_file(self, path: str, data: bytes) -> None:
        return None

    def write_cover(self, book_dir: str, data: bytes) -> None:
        return None

    def move(self, old_path: str, new_path: str) -> None:
        return None

    def delete(self, path: str) -> None:
        return None


class FakeConverter:
    def convert(
        self,
        input_path: str,
        output_path: str,
        *,
        opf: bytes | None = None,
        cover: bytes | None = None,
        on_progress: Callable[[float], None] | None = None,
    ) -> ConversionResult:
        return ConversionResult(ok=True, output_format="EPUB")


class FakeInjector:
    def inject(self, file_path: str, book: Book) -> None:
        return None


class FakeExtractor:
    def extract(
        self, file_path: str, extension: str, *, fallback_title: str | None = None
    ) -> BookMeta:
        return BookMeta(title=fallback_title or "x", extension=extension)


class FakeMailer:
    def send(self, message: EmailMessage) -> None:
        return None

    def test(self, recipient: str) -> None:
        return None


class FakeSource:
    name = "fake"

    def search(self, query: str, *, page: int, limit: int) -> tuple[ExternalBook, ...]:
        return ()

    def get_details(self, external_id: str) -> ExternalBook:
        return ExternalBook(source=self.name, external_id=external_id, title="x")

    def download(self, external_id: str) -> tuple[str, bytes]:
        return ("x.epub", b"")

    def quota(self) -> Quota | None:
        return None


def test_repository_conforms() -> None:
    repo: MetadataRepository = FakeRepository()
    assert isinstance(repo, MetadataRepository)


def test_storage_conforms() -> None:
    storage: FileStorage = FakeStorage()
    assert isinstance(storage, FileStorage)


def test_converter_conforms() -> None:
    converter: Converter = FakeConverter()
    assert isinstance(converter, Converter)


def test_injector_conforms() -> None:
    injector: MetadataInjector = FakeInjector()
    assert isinstance(injector, MetadataInjector)


def test_extractor_conforms() -> None:
    extractor: MetadataExtractor = FakeExtractor()
    assert isinstance(extractor, MetadataExtractor)


def test_mailer_conforms() -> None:
    mailer: Mailer = FakeMailer()
    assert isinstance(mailer, Mailer)


def test_source_conforms() -> None:
    source: DataSource = FakeSource()
    assert isinstance(source, DataSource)


def test_source_download_shape() -> None:
    # Sanity on the download contract: (filename, bytes).
    filename, data = FakeSource().download("abc")
    assert isinstance(filename, str)
    assert isinstance(data, bytes)


def test_extractor_returns_book_meta() -> None:
    meta = FakeExtractor().extract("books/x.epub", ".epub")
    assert isinstance(meta, BookMeta)
    assert meta.pubdate is None or isinstance(meta.pubdate, datetime)
