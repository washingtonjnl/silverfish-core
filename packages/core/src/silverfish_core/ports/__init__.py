"""Ports: the interfaces the core defines and adapters implement.

The core depends only on these abstractions (structural ``Protocol`` types), not
on concrete persistence, storage, binaries, mail servers or external sources. A
``LibraryService`` is assembled by injecting adapters that conform to them.
"""

from silverfish_core.ports.converter import Converter
from silverfish_core.ports.extractor import MetadataExtractor
from silverfish_core.ports.injector import MetadataInjector
from silverfish_core.ports.mailer import Mailer
from silverfish_core.ports.repository import MetadataRepository
from silverfish_core.ports.source import DataSource
from silverfish_core.ports.storage import DownloadLinkProvider, FileStorage

__all__ = [
    "Converter",
    "DataSource",
    "DownloadLinkProvider",
    "FileStorage",
    "Mailer",
    "MetadataExtractor",
    "MetadataInjector",
    "MetadataRepository",
]
