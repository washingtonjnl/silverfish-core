"""Pure-Python metadata extractor.

Reads metadata (and cover) out of book files without any Calibre binary. EPUB is
parsed by reading the OPF inside the ZIP. Unknown formats and unreadable files
fall back to a filename-derived title rather than raising, so a single bad
upload never breaks the flow.

Security: EPUBs are untrusted input. We read entries by exact name (no path
traversal out of the archive), cap how much we read, and parse XML with
defusedxml to neutralise entity-expansion / XXE attacks.
"""

import posixpath
import zipfile
from pathlib import Path
from xml.etree.ElementTree import Element, ParseError

# defusedxml hardens XML parsing against entity-expansion / XXE attacks. EPUB
# content is untrusted, so we never use the stdlib parser on it directly.
from defusedxml.ElementTree import fromstring as defused_fromstring

from silverfish_core.adapters._opf import parse_opf
from silverfish_core.ports.types import BookMeta

_CONTAINER_PATH = "META-INF/container.xml"
_OPF_NS = "http://www.idpf.org/2007/opf"
_CONTAINER_NS = "urn:oasis:names:tc:opendocument:xmlns:container"

# Defensive cap: an OPF document larger than this is not a real metadata file.
_MAX_OPF_BYTES = 4 * 1024 * 1024
# Covers above this are rejected to avoid pulling a huge entry into memory.
_MAX_COVER_BYTES = 32 * 1024 * 1024


class PythonMetadataExtractor:
    """Extract metadata from EPUB natively; fall back for everything else.

    Only EPUB (ZIP + OPF) is parsed in pure Python, which keeps EPUB upload free
    of any Calibre binary. Other formats (PDF, MOBI, AZW3, ...) fall back to a
    title derived from the original upload name here; their rich metadata and
    covers are read via the Calibre ``ebook-meta`` binary in a later step.
    """

    def extract(
        self, file_path: str, extension: str, *, fallback_title: str | None = None
    ) -> BookMeta:
        ext = extension.lower()
        fallback = self._fallback(file_path, ext, fallback_title)
        if ext in {".epub", ".kepub"}:
            try:
                return self._extract_epub(file_path, ext, fallback)
            except (zipfile.BadZipFile, KeyError, ParseError, OSError, ValueError):
                return fallback
        return fallback

    def _fallback(self, file_path: str, ext: str, fallback_title: str | None) -> BookMeta:
        # Prefer the caller-supplied original name; never leak a temp-file stem.
        title = fallback_title.strip() if fallback_title and fallback_title.strip() else None
        return BookMeta(title=title or Path(file_path).stem, extension=ext)

    def _extract_epub(self, file_path: str, ext: str, fallback: BookMeta) -> BookMeta:
        with zipfile.ZipFile(file_path) as zf:
            opf_path = self._find_opf_path(zf)
            if opf_path is None:
                return fallback
            opf_root = self._parse_entry(zf, opf_path)
            if opf_root is None:
                return fallback

            cover = self._cover(zf, opf_root, opf_path)
            return parse_opf(opf_root, extension=ext, fallback_title=fallback.title, cover=cover)

    def _find_opf_path(self, zf: zipfile.ZipFile) -> str | None:
        if _CONTAINER_PATH not in zf.namelist():
            return None
        root = self._parse_entry(zf, _CONTAINER_PATH)
        if root is None:
            return None
        rootfile = root.find(f"{{{_CONTAINER_NS}}}rootfiles/{{{_CONTAINER_NS}}}rootfile")
        if rootfile is None:
            return None
        return rootfile.get("full-path")

    def _parse_entry(self, zf: zipfile.ZipFile, name: str) -> Element | None:
        info = zf.getinfo(name)
        if info.file_size > _MAX_OPF_BYTES:
            return None
        data = zf.read(name)
        return defused_fromstring(data)

    def _cover(self, zf: zipfile.ZipFile, opf_root: Element, opf_path: str) -> bytes | None:
        metadata = opf_root.find(f"{{{_OPF_NS}}}metadata")
        manifest = opf_root.find(f"{{{_OPF_NS}}}manifest")
        if metadata is None or manifest is None:
            return None

        cover_id: str | None = None
        for meta in metadata.findall(f"{{{_OPF_NS}}}meta"):
            if meta.get("name") == "cover":
                cover_id = meta.get("content")
                break
        if cover_id is None:
            return None

        href: str | None = None
        for item in manifest.findall(f"{{{_OPF_NS}}}item"):
            if item.get("id") == cover_id:
                href = item.get("href")
                break
        if href is None:
            return None

        # Cover href is relative to the OPF's directory inside the archive.
        # posixpath.normpath collapses any "./"/".." so the lookup stays inside
        # the archive's namelist (no path-traversal surprises).
        opf_dir = posixpath.dirname(opf_path)
        candidate = posixpath.normpath(posixpath.join(opf_dir, href))
        if candidate not in zf.namelist():
            return None
        info = zf.getinfo(candidate)
        if info.file_size > _MAX_COVER_BYTES:
            return None
        return zf.read(candidate)
