"""Tests for the metadata-refresh endpoint and convert source selection.

Written before the implementation (TDD). Refresh re-reads a chosen format and
patches the book. Convert can omit source_format, in which case the API picks
the best available source by priority. Uses a real library + real binaries
(skipped when ebook-meta/ebook-convert are absent).
"""

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import create_app
from silverfish_core.adapters.calibre_binaries import CalibreBinaries

CORE_TESTS = Path(__file__).parents[2] / "core" / "tests"
FIXTURE_DB = CORE_TESTS / "fixtures" / "calibre_library" / "metadata.db"
RICH_EPUB = CORE_TESTS / "fixtures" / "ebooks" / "rich.epub"

_HAS_META = CalibreBinaries().ebook_meta is not None


@pytest.fixture
def library(tmp_path: Path) -> Path:
    lib = tmp_path / "library"
    lib.mkdir()
    shutil.copy(FIXTURE_DB, lib / "metadata.db")
    book_dir = lib / "Jane Austen" / "The Great Book (1)"
    book_dir.mkdir(parents=True)
    # Put a metadata-rich EPUB on disk as book 1's EPUB.
    shutil.copy(RICH_EPUB, book_dir / "The Great Book - Jane Austen.epub")
    return lib


@pytest.fixture
def client(library: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(library))
    with TestClient(create_app()) as test_client:
        yield test_client


class TestRefresh:
    def test_refreshes_title_from_epub(self, client: TestClient) -> None:
        # Book 1's title in the DB is "The Great Book"; the EPUB on disk says
        # "The Hobbit". Refreshing from EPUB pulls that in.
        response = client.post("/books/1/refresh-metadata", json={"source_format": "EPUB"})
        assert response.status_code == 200
        assert response.json()["title"] == "The Hobbit"

    def test_404_for_missing_book(self, client: TestClient) -> None:
        response = client.post("/books/999999/refresh-metadata", json={"source_format": "EPUB"})
        assert response.status_code == 404

    def test_400_for_missing_format(self, client: TestClient) -> None:
        response = client.post("/books/1/refresh-metadata", json={"source_format": "MOBI"})
        assert response.status_code == 400


@pytest.mark.skipif(not _HAS_META, reason="ebook-convert not installed")
class TestConvertSourceOptional:
    def test_convert_without_source_picks_available(self, client: TestClient) -> None:
        # Only EPUB exists; omitting source_format should still work.
        response = client.post("/books/1/convert", json={"target_format": "PDF"})
        assert response.status_code == 202

    def test_convert_with_unavailable_source_is_400(self, client: TestClient) -> None:
        response = client.post(
            "/books/1/convert", json={"source_format": "MOBI", "target_format": "PDF"}
        )
        assert response.status_code == 400
