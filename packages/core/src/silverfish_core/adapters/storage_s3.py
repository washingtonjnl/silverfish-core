"""S3 (or S3-compatible) implementation of the ``FileStorage`` port.

Maps library-relative paths to object keys under an optional prefix, in a single
bucket. Implements the same contract as local storage: read/write a book file,
write a cover, move (rename) and delete — where "directory" operations act on a
key prefix, since S3 has no real directories. Path traversal (``..``, absolute
paths, empty) is rejected before any S3 call.

Credentials come from the boto3 client the adapter is given (built from env/IAM
by the factory). A SaaS can hand each tenant a differently-configured client;
this adapter is tenant-agnostic. ``boto3`` is an optional dependency
(``silverfish-core[s3]``).
"""

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mypy_boto3_s3.client import S3Client

# Forbidden path patterns, mirroring local storage's traversal guard (no
# filesystem here, so the checks are purely lexical on the relative path).
_PARENT = ".."


class S3Storage:
    """Store book files and covers as objects in an S3 bucket."""

    def __init__(self, *, bucket: str, client: "S3Client", prefix: str = "") -> None:
        self._bucket = bucket
        self._client = client
        # Normalise the prefix to "" or "something/" (no leading slash).
        self._prefix = f"{prefix.strip('/')}/" if prefix.strip("/") else ""

    def _key(self, path: str) -> str:
        """Map a library-relative *path* to an object key under the prefix.

        Rejects empty paths, absolute paths and any ``..`` traversal, so a key
        can never escape the configured prefix.
        """
        if not path or not path.strip():
            msg = "Path must not be empty"
            raise ValueError(msg)
        if path.startswith("/"):
            msg = f"Absolute paths are invalid: {path!r}"
            raise ValueError(msg)
        parts = [p for p in path.split("/") if p not in ("", ".")]
        if _PARENT in parts:
            msg = f"Path escapes the storage prefix (traversal): {path!r}"
            raise ValueError(msg)
        return self._prefix + "/".join(parts)

    def read_book_file(self, path: str) -> bytes:
        key = self._key(path)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
        except self._client.exceptions.NoSuchKey as exc:
            raise FileNotFoundError(path) from exc
        except self._client.exceptions.ClientError as exc:  # pragma: no cover - 404 path
            if _is_not_found(exc):
                raise FileNotFoundError(path) from exc
            raise
        body: bytes = response["Body"].read()
        return body

    def write_book_file(self, path: str, data: bytes) -> None:
        self._client.put_object(Bucket=self._bucket, Key=self._key(path), Body=data)

    def write_cover(self, book_dir: str, data: bytes) -> None:
        # book_dir is validated by _key; "cover.jpg" cannot add traversal.
        key = self._key(book_dir) + "/cover.jpg"
        self._client.put_object(Bucket=self._bucket, Key=key, Body=data)

    def move(self, old_path: str, new_path: str) -> None:
        """Relocate an object, or every object under a "directory" prefix."""
        old_key = self._key(old_path)
        new_key = self._key(new_path)
        moved_any = False
        for key in self._list(old_key):
            suffix = key[len(old_key) :]
            self._client.copy_object(
                Bucket=self._bucket,
                Key=new_key + suffix,
                CopySource={"Bucket": self._bucket, "Key": key},
            )
            self._client.delete_object(Bucket=self._bucket, Key=key)
            moved_any = True
        if not moved_any:
            raise FileNotFoundError(old_path)

    def delete(self, path: str) -> None:
        """Delete an object, or every object under a "directory" prefix.

        A path that matches nothing is a no-op (mirrors local storage).
        """
        key = self._key(path)
        for found in self._list(key):
            self._client.delete_object(Bucket=self._bucket, Key=found)

    def presigned_url(self, path: str, *, expires_in: int) -> str:
        """Return a time-limited URL that downloads the object directly from S3.

        Lets a large export be downloaded straight from S3 (resumable, off the
        API server) for *expires_in* seconds. The path is traversal-checked like
        any other.
        """
        key = self._key(path)
        url: str = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )
        return url

    def _list(self, key: str) -> list[str]:
        """Return the object keys for *key* exactly, plus any under ``key/``.

        Lets a single name address both a file (``a/b.epub``) and a directory
        (``a/b.epub`` would not, but ``dir`` matches ``dir/...``). The exact key
        is included so single-file move/delete works.
        """
        keys: list[str] = []
        # Objects under the "directory" key/.
        prefixes = {f"{key}/"}
        # The exact object (a file), if present.
        if _object_exists(self._client, self._bucket, key):
            keys.append(key)
        for prefix in prefixes:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
                keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys


def _object_exists(client: "S3Client", bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
    except client.exceptions.ClientError:
        return False
    return True


def _is_not_found(exc: Any) -> bool:
    code = exc.response.get("Error", {}).get("Code", "")
    return code in ("404", "NoSuchKey", "NotFound")
