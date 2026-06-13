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

from silverfish_core.ports.types import BookMeta

_CONTAINER_PATH = "META-INF/container.xml"
_OPF_NS = "http://www.idpf.org/2007/opf"
_DC_NS = "http://purl.org/dc/elements/1.1/"
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

            metadata = opf_root.find(f"{{{_OPF_NS}}}metadata")
            if metadata is None:
                return fallback

            title = self._text(metadata.find(f"{{{_DC_NS}}}title")) or fallback.title
            authors = tuple(
                t for e in metadata.findall(f"{{{_DC_NS}}}creator") if (t := self._text(e))
            )
            languages = tuple(
                t for e in metadata.findall(f"{{{_DC_NS}}}language") if (t := self._text(e))
            )
            tags = tuple(
                t for e in metadata.findall(f"{{{_DC_NS}}}subject") if (t := self._text(e))
            )
            publisher = self._text(metadata.find(f"{{{_DC_NS}}}publisher"))
            description = self._text(metadata.find(f"{{{_DC_NS}}}description"))
            identifiers = self._identifiers(metadata)
            series, series_index = self._series(metadata)
            cover = self._cover(zf, opf_root, opf_path)

            return BookMeta(
                title=title,
                extension=ext,
                authors=authors,
                cover=cover,
                description=description,
                tags=tags,
                series=series,
                series_index=series_index,
                languages=languages,
                publisher=publisher,
                identifiers=identifiers,
            )

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

    def _text(self, element: Element | None) -> str | None:
        if element is None or element.text is None:
            return None
        stripped = element.text.strip()
        return stripped or None

    def _identifiers(self, metadata: Element) -> tuple[tuple[str, str], ...]:
        result: list[tuple[str, str]] = []
        for element in metadata.findall(f"{{{_DC_NS}}}identifier"):
            scheme = element.get(f"{{{_OPF_NS}}}scheme")
            value = self._text(element)
            # Skip the internal uuid/book-id identifier; keep real schemes.
            if scheme and value and scheme.lower() != "uuid":
                result.append((scheme.lower(), value))
        return tuple(result)

    def _series(self, metadata: Element) -> tuple[str | None, float | None]:
        series: str | None = None
        index: float | None = None
        for meta in metadata.findall(f"{{{_OPF_NS}}}meta"):
            name = meta.get("name")
            content = meta.get("content")
            if name == "calibre:series" and content:
                series = content
            elif name == "calibre:series_index" and content:
                try:
                    index = float(content)
                except ValueError:
                    index = None
        return series, index

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
