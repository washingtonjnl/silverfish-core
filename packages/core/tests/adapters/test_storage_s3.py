"""Tests for the S3 ``FileStorage`` adapter (TDD).

Runs against an in-process S3 mock (moto), so no AWS account or network is
needed. The adapter maps library-relative paths to object keys under an optional
prefix, and implements the same contract as local storage: read/write a book
file, write a cover, move (rename) and delete — including deleting a whole
"directory" (key prefix). Path traversal is rejected before any call.
"""

from collections.abc import Iterator
from typing import Any

import boto3
import pytest
from moto import mock_aws

from silverfish_core.adapters.storage_s3 import S3Storage
from silverfish_core.ports import FileStorage

_BUCKET = "silverfish-test"


@pytest.fixture
def s3_client() -> Iterator[Any]:
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=_BUCKET)
        yield client


@pytest.fixture
def storage(s3_client: Any) -> S3Storage:
    return S3Storage(bucket=_BUCKET, client=s3_client, prefix="library")


class TestConformance:
    def test_is_a_file_storage(self, storage: S3Storage) -> None:
        assert isinstance(storage, FileStorage)


class TestReadWrite:
    def test_write_then_read(self, storage: S3Storage) -> None:
        storage.write_book_file("Author/Title (1)/book.epub", b"EPUBDATA")
        assert storage.read_book_file("Author/Title (1)/book.epub") == b"EPUBDATA"

    def test_read_missing_raises(self, storage: S3Storage) -> None:
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("nope/missing.epub")

    def test_write_overwrites(self, storage: S3Storage) -> None:
        storage.write_book_file("a/b.epub", b"first")
        storage.write_book_file("a/b.epub", b"second")
        assert storage.read_book_file("a/b.epub") == b"second"

    def test_object_lands_under_prefix(self, storage: S3Storage, s3_client: Any) -> None:
        storage.write_book_file("Author/Title (1)/book.epub", b"x")
        # The key carries the configured prefix.
        keys = [o["Key"] for o in s3_client.list_objects_v2(Bucket=_BUCKET)["Contents"]]
        assert "library/Author/Title (1)/book.epub" in keys


class TestCover:
    def test_write_cover(self, storage: S3Storage) -> None:
        storage.write_cover("Author/Title (1)", b"JPEGDATA")
        assert storage.read_book_file("Author/Title (1)/cover.jpg") == b"JPEGDATA"


class TestMove:
    def test_move_relocates_object(self, storage: S3Storage) -> None:
        storage.write_book_file("old/book.epub", b"DATA")
        storage.move("old/book.epub", "new/book.epub")
        assert storage.read_book_file("new/book.epub") == b"DATA"
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("old/book.epub")

    def test_move_directory(self, storage: S3Storage) -> None:
        # Moving a "directory" relocates every object beneath it.
        storage.write_book_file("Author/Old Title (1)/book.epub", b"DATA")
        storage.write_book_file("Author/Old Title (1)/cover.jpg", b"COVER")
        storage.move("Author/Old Title (1)", "Author/New Title (1)")
        assert storage.read_book_file("Author/New Title (1)/book.epub") == b"DATA"
        assert storage.read_book_file("Author/New Title (1)/cover.jpg") == b"COVER"


class TestDelete:
    def test_delete_single_object(self, storage: S3Storage) -> None:
        storage.write_book_file("a/b.epub", b"DATA")
        storage.delete("a/b.epub")
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("a/b.epub")

    def test_delete_directory_removes_all(self, storage: S3Storage) -> None:
        storage.write_book_file("dir (1)/book.epub", b"DATA")
        storage.write_book_file("dir (1)/cover.jpg", b"COVER")
        storage.delete("dir (1)")
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("dir (1)/book.epub")
        with pytest.raises(FileNotFoundError):
            storage.read_book_file("dir (1)/cover.jpg")

    def test_delete_missing_is_noop(self, storage: S3Storage) -> None:
        storage.delete("not/there.epub")  # must not raise


class TestPresignedUrl:
    def test_generates_a_url_for_an_object(self, storage: S3Storage) -> None:
        storage.write_book_file("exports/lib.zip", b"ZIPDATA")
        url = storage.presigned_url("exports/lib.zip", expires_in=600)
        assert url.startswith("http")
        # The URL targets the object key (under the prefix) and is signed.
        assert "lib.zip" in url
        assert "Signature" in url or "X-Amz-Signature" in url

    def test_url_respects_traversal_guard(self, storage: S3Storage) -> None:
        with pytest.raises(ValueError, match=r"raversal|escape"):
            storage.presigned_url("../escape.zip", expires_in=600)


class TestTraversal:
    def test_absolute_path_rejected(self, storage: S3Storage) -> None:
        with pytest.raises(ValueError, match="bsolute"):
            storage.write_book_file("/etc/passwd", b"x")

    def test_parent_traversal_rejected(self, storage: S3Storage) -> None:
        with pytest.raises(ValueError, match=r"raversal|escape"):
            storage.read_book_file("../outside.epub")

    def test_empty_path_rejected(self, storage: S3Storage) -> None:
        with pytest.raises(ValueError, match="empty"):
            storage.read_book_file("")
