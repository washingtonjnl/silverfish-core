"""End-to-end test of base62 public ids in standalone mode.

In standalone mode the core mints large Snowflake ids. The API must expose them
as short base62 strings and accept those same strings back on by-id routes —
the integer never leaks into a URL, and the round-trip resolves the same book. A
malformed id is a 404, not a 422.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from silverfish_api.app import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    # Standalone mode (the default): the core owns a fresh SQLite library.
    monkeypatch.setenv("SILVERFISH_LIBRARY_DIR", str(tmp_path / "lib"))
    with TestClient(create_app()) as test_client:
        yield test_client


def _upload(client: TestClient) -> str:
    epub = _minimal_epub()
    response = client.post("/books", files={"file": ("hobbit.epub", epub, "application/epub+zip")})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


class TestRoundTrip:
    def test_created_id_is_short_base62_string(self, client: TestClient) -> None:
        book_id = _upload(client)
        # A Snowflake id rendered in base62 is short, non-numeric-looking and
        # nothing like the full decimal integer.
        assert isinstance(book_id, str)
        assert 1 <= len(book_id) <= 12
        assert book_id.isalnum()

    def test_get_by_public_id_resolves_same_book(self, client: TestClient) -> None:
        book_id = _upload(client)
        response = client.get(f"/books/{book_id}")
        assert response.status_code == 200
        assert response.json()["id"] == book_id

    def test_malformed_id_is_404(self, client: TestClient) -> None:
        # '-' is outside the base62 alphabet, so it cannot name any book.
        assert client.get("/books/not-a-valid-id").status_code == 404


def _minimal_epub() -> bytes:
    """Build the smallest EPUB the native extractor accepts."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("mimetype", "application/epub+zip")
        zf.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?>'
            '<container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        zf.writestr(
            "content.opf",
            '<?xml version="1.0"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
            'unique-identifier="id"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/">'
            "<dc:title>The Hobbit</dc:title>"
            "<dc:creator>J. R. R. Tolkien</dc:creator>"
            '<dc:identifier id="id">urn:uuid:test</dc:identifier>'
            "</metadata><manifest/><spine/></package>",
        )
    return buffer.getvalue()
