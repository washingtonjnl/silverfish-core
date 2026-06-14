"""Shared OPF metadata parsing.

The OPF (Open Packaging Format) is the XML metadata document inside an EPUB and
also what ``ebook-meta --to-opf`` produces for any format. Both the native EPUB
extractor and the ebook-meta extractor parse it with these helpers, so the
mapping to ``BookMeta`` lives in one place.

Security: OPF content is untrusted; callers parse it with defusedxml.
"""

from xml.etree.ElementTree import Element

from silverfish_core.ports.types import BookMeta

OPF_NS = "http://www.idpf.org/2007/opf"
DC_NS = "http://purl.org/dc/elements/1.1/"


def parse_opf(
    root: Element, *, extension: str, fallback_title: str, cover: bytes | None
) -> BookMeta:
    """Map an OPF ``<package>`` element to a ``BookMeta``.

    *fallback_title* is used when the OPF has no usable title. *cover* (if any)
    is attached as-is; cover extraction differs by source so it is passed in.
    """
    metadata = root.find(f"{{{OPF_NS}}}metadata")
    if metadata is None:
        return BookMeta(title=fallback_title, extension=extension, cover=cover)

    title = _text(metadata.find(f"{{{DC_NS}}}title")) or fallback_title
    authors = tuple(t for e in metadata.findall(f"{{{DC_NS}}}creator") if (t := _text(e)))
    languages = tuple(t for e in metadata.findall(f"{{{DC_NS}}}language") if (t := _text(e)))
    tags = tuple(t for e in metadata.findall(f"{{{DC_NS}}}subject") if (t := _text(e)))
    publisher = _text(metadata.find(f"{{{DC_NS}}}publisher"))
    description = _text(metadata.find(f"{{{DC_NS}}}description"))
    series, series_index = _series(metadata)

    return BookMeta(
        title=title,
        extension=extension,
        authors=authors,
        cover=cover,
        description=description,
        tags=tags,
        series=series,
        series_index=series_index,
        languages=languages,
        publisher=publisher,
        identifiers=_identifiers(metadata),
    )


def find_metadata(root: Element) -> Element | None:
    return root.find(f"{{{OPF_NS}}}metadata")


def _text(element: Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    stripped = element.text.strip()
    return stripped or None


def _identifiers(metadata: Element) -> tuple[tuple[str, str], ...]:
    result: list[tuple[str, str]] = []
    for element in metadata.findall(f"{{{DC_NS}}}identifier"):
        scheme = element.get(f"{{{OPF_NS}}}scheme")
        value = _text(element)
        # Skip the internal calibre/uuid id; keep real schemes (isbn, google...).
        if scheme and value and scheme.lower() not in {"uuid", "calibre"}:
            result.append((scheme.lower(), value))
    return tuple(result)


def _series(metadata: Element) -> tuple[str | None, float | None]:
    series: str | None = None
    index: float | None = None
    for meta in metadata.findall(f"{{{OPF_NS}}}meta"):
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
