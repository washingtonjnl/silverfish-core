"""Concrete Google Drive client backing ``GDriveStorage``.

Wraps ``googleapiclient`` to satisfy the small ``DriveClient`` protocol the
storage adapter depends on (create folder, find child, upload, download, list,
delete, move, share). Credentials arrive pre-resolved (an OAuth refresh token);
obtaining them — the consent flow — is the product's job, not the core's.

This talks to the real Drive API, so it is covered by manual integration testing
rather than the unit suite (which uses an in-memory fake). ``google-api-python-
client`` / ``google-auth`` are the optional ``gdrive`` extra.
"""

import io
from typing import Any

_FOLDER_MIME = "application/vnd.google-apps.folder"


class GoogleDriveClient:
    """A thin ``DriveClient`` over the Google Drive v3 API."""

    # ``service`` is a googleapiclient Resource — an untyped, dynamically-built
    # object — so it is typed Any deliberately; our own methods stay typed
    # against the DriveClient protocol.
    def __init__(self, service: Any) -> None:
        self._service = service

    def find_child(self, name: str, parent_id: str) -> str | None:
        # Drive query: a non-trashed child of parent with this exact name.
        safe = name.replace("'", "\\'")
        query = f"name = '{safe}' and '{parent_id}' in parents and trashed = false"
        response = (
            self._service.files()
            .list(q=query, fields="files(id)", pageSize=1, spaces="drive")
            .execute()
        )
        files = response.get("files", [])
        return str(files[0]["id"]) if files else None

    def create_folder(self, name: str, parent_id: str) -> str:
        metadata = {"name": name, "mimeType": _FOLDER_MIME, "parents": [parent_id]}
        created = self._service.files().create(body=metadata, fields="id").execute()
        return str(created["id"])

    def upload(self, name: str, parent_id: str, data: bytes) -> str:
        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(io.BytesIO(data), mimetype="application/octet-stream")
        existing = self.find_child(name, parent_id)
        if existing is not None:
            self._service.files().update(fileId=existing, media_body=media).execute()
            return existing
        metadata = {"name": name, "parents": [parent_id]}
        created = (
            self._service.files().create(body=metadata, media_body=media, fields="id").execute()
        )
        return str(created["id"])

    def download(self, file_id: str) -> bytes:
        from googleapiclient.http import MediaIoBaseDownload

        buffer = io.BytesIO()
        request = self._service.files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def list_children(self, parent_id: str) -> list[tuple[str, str, bool]]:
        children: list[tuple[str, str, bool]] = []
        page_token: str | None = None
        query = f"'{parent_id}' in parents and trashed = false"
        while True:
            response = (
                self._service.files()
                .list(
                    q=query,
                    fields="nextPageToken, files(id, name, mimeType)",
                    pageToken=page_token,
                    spaces="drive",
                )
                .execute()
            )
            for f in response.get("files", []):
                children.append((str(f["id"]), str(f["name"]), f["mimeType"] == _FOLDER_MIME))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
        return children

    def delete(self, file_id: str) -> None:
        self._service.files().delete(fileId=file_id).execute()

    def move(self, file_id: str, new_parent_id: str, new_name: str) -> None:
        # Replace all parents with the new one and rename in a single update.
        current = self._service.files().get(fileId=file_id, fields="parents").execute()
        old_parents = ",".join(current.get("parents", []))
        self._service.files().update(
            fileId=file_id,
            addParents=new_parent_id,
            removeParents=old_parents,
            body={"name": new_name},
        ).execute()

    def share_link(self, file_id: str, *, expires_in: int) -> str:
        # Make the file readable by anyone with the link, then return that link.
        # (Drive's per-permission expiry is limited; the export-purge sweep is the
        # real guarantee — it deletes the file at TTL.)
        self._service.permissions().create(
            fileId=file_id, body={"type": "anyone", "role": "reader"}
        ).execute()
        meta = self._service.files().get(fileId=file_id, fields="webContentLink").execute()
        link: Any = meta.get("webContentLink") or f"https://drive.google.com/uc?id={file_id}"
        return str(link)
