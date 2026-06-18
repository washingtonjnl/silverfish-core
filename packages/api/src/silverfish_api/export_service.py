"""Export service: run the Calibre export, zip it, and prepare delivery.

Orchestrates the boundary work around the core ``CalibreExporter``: it exports
into a temporary directory, zips that directory, registers the zip in the
``ExportStore`` under a token, and discards the intermediate tree so only the
zip survives. It also builds the "your export is ready" email carrying the
download link. The zip is ephemeral — the store deletes it once its TTL passes.

Building the zip needs the bytes on disk somewhere; that is unavoidable. What we
guarantee is that nothing lingers: the unzipped tree is removed immediately, and
the zip itself is time-limited.
"""

import shutil
import zipfile
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from silverfish_api.export_store import ExportStore


class _Exporter(Protocol):
    """The slice of CalibreExporter this service uses."""

    def export(self, destination: Path) -> "_ExportSummary": ...


class _ExportSummary(Protocol):
    book_count: int


@dataclass(frozen=True, slots=True)
class ExportRunResult:
    """Outcome of a completed export run."""

    token: str
    book_count: int


class ExportService:
    """Run a Calibre export and turn it into a downloadable, expiring zip."""

    def __init__(
        self,
        *,
        exporter: _Exporter,
        store: ExportStore,
        work_dir: Path,
        download_base_url: str,
    ) -> None:
        self._exporter = exporter
        self._store = store
        self._work_dir = work_dir
        self._download_base_url = download_base_url.rstrip("/")

    def run_export(self) -> ExportRunResult:
        """Export the library, zip it, register the zip, and return its token.

        The intermediate (unzipped) directory is always removed; only the zip
        remains, held by the store until its TTL expires.
        """
        self._work_dir.mkdir(parents=True, exist_ok=True)
        run_dir = Path(self._work_dir / _unique_name("export"))
        library_dir = run_dir / "library"
        zip_path = run_dir.with_suffix(".zip")
        try:
            summary = self._exporter.export(library_dir)
            self._zip_directory(library_dir, zip_path)
        finally:
            # The unzipped tree never lingers, even if zipping failed.
            shutil.rmtree(run_dir, ignore_errors=True)
        token = self._store.register(zip_path)
        return ExportRunResult(token=token, book_count=summary.book_count)

    def build_ready_email(self, *, to_email: str, token: str) -> EmailMessage:
        """Build the "export ready" email with the time-limited download link."""
        link = f"{self._download_base_url}/{token}"
        message = EmailMessage()
        message["Subject"] = "Your Silverfish library export is ready"
        message["To"] = to_email
        message.set_content(
            "Your library export is ready to download.\n\n"
            f"Download it here: {link}\n\n"
            "The link is temporary and will expire after a while, so download it soon."
        )
        return message

    def _zip_directory(self, source: Path, zip_path: Path) -> None:
        """Zip *source* into *zip_path*, storing paths relative to *source*."""
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(source.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(source))


def _unique_name(prefix: str) -> str:
    """A short unique directory name (no clock/random needed: uses uuid4)."""
    import uuid

    return f"{prefix}-{uuid.uuid4().hex}"
