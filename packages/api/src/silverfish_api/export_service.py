"""Export service: run the Calibre export, zip it, and prepare delivery.

Orchestrates the boundary work around the core ``CalibreExporter``: it exports
into a temporary directory, zips that directory, and produces a download URL plus
the "export ready" email. Delivery adapts to the storage backend:

* presigned-capable storage (S3) — the zip is uploaded to storage and the URL is
  a direct, time-limited link to it, so a large download bypasses the API server.
* otherwise (local disk) — the zip is registered in the ``ExportStore`` under a
  token and served by the API's download route.

Either way the intermediate (unzipped) tree is removed; the zip is ephemeral —
expired by the store's TTL (local) or by the presigned URL's expiry (S3).
"""

import shutil
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from silverfish_api.export_store import ExportStore
from silverfish_core.ports import FileStorage, PresignedDownload


class _Exporter(Protocol):
    """The slice of CalibreExporter this service uses."""

    def export(
        self, destination: Path, book_ids: "Sequence[int] | None" = None
    ) -> "_ExportSummary": ...


class _ExportSummary(Protocol):
    book_count: int


@dataclass(frozen=True, slots=True)
class ExportRunResult:
    """Outcome of a completed export run."""

    download_url: str
    book_count: int


class ExportService:
    """Run a Calibre export and turn it into a downloadable, expiring zip."""

    def __init__(
        self,
        *,
        exporter: _Exporter,
        store: ExportStore,
        storage: FileStorage,
        work_dir: Path,
        public_base_url: str,
    ) -> None:
        self._exporter = exporter
        self._store = store
        self._storage = storage
        self._work_dir = work_dir
        self._public_base_url = public_base_url.rstrip("/")

    @property
    def delivers_absolute_links(self) -> bool:
        """Whether emailed links will be absolute (clickable).

        Requires a configured public base URL for the local download route; the
        presigned case always yields an absolute URL from the storage backend.
        """
        if isinstance(self._storage, PresignedDownload):
            return True
        return self._public_base_url.startswith(("http://", "https://"))

    def run_export(self, book_ids: "Sequence[int] | None" = None) -> ExportRunResult:
        """Export the library, zip it, and return the download URL.

        *book_ids* selects which books to export (``None`` = the whole library).
        The intermediate (unzipped) directory is always removed.
        """
        self._work_dir.mkdir(parents=True, exist_ok=True)
        run_dir = Path(self._work_dir / _unique_name("export"))
        library_dir = run_dir / "library"
        zip_path = run_dir.with_suffix(".zip")
        try:
            summary = self._exporter.export(library_dir, book_ids)
            self._zip_directory(library_dir, zip_path)
            url = self._deliver(zip_path)
        finally:
            # Neither the unzipped tree nor (in the S3 case) the local zip lingers.
            shutil.rmtree(run_dir, ignore_errors=True)
        return ExportRunResult(download_url=url, book_count=summary.book_count)

    def build_ready_email(self, *, to_email: str, download_url: str) -> EmailMessage:
        """Build the "export ready" email with the time-limited download link.

        The expiry window is formatted ``{h}h{mm}`` from the store's TTL (e.g. a
        24-hour TTL reads ``24h00``, ten minutes ``0h10``).
        """
        total_minutes = max(1, round(self._store.ttl_seconds / 60))
        window = f"{total_minutes // 60}h{total_minutes % 60:02d}"
        message = EmailMessage()
        message["Subject"] = "Your Silverfish library export is ready"
        message["To"] = to_email
        message.set_content(
            "Your library export is ready to download.\n\n"
            f"Download it here: {download_url}\n\n"
            f"The link is temporary and expires in {window}, so download it soon."
        )
        return message

    # --- delivery -----------------------------------------------------------

    def _deliver(self, zip_path: Path) -> str:
        """Place the zip where it can be downloaded and return its URL.

        Uploads to storage and returns a presigned URL when the backend supports
        it; otherwise registers the local file under a token and points at the
        API download route. The local zip is removed after a presigned upload.
        """
        if isinstance(self._storage, PresignedDownload):
            token = _unique_name("export")
            key = f"exports/{token}.zip"
            self._storage.write_book_file(key, zip_path.read_bytes())
            zip_path.unlink(missing_ok=True)
            return self._storage.presigned_url(key, expires_in=int(self._store.ttl_seconds))
        token = self._store.register(zip_path)
        return f"{self._public_base_url}/export/download/{token}"

    def _zip_directory(self, source: Path, zip_path: Path) -> None:
        """Zip *source* into *zip_path*, storing paths relative to *source*."""
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(source))


def _unique_name(prefix: str) -> str:
    """A short unique name (no clock/random global needed: uses uuid4)."""
    import uuid

    return f"{prefix}-{uuid.uuid4().hex}"
