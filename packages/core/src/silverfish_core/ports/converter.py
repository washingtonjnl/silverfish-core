"""Port: format conversion.

Implemented by an adapter wrapping the native ``ebook-convert`` binary. The core
only knows it can turn one file into another format and observe progress.
"""

from collections.abc import Callable
from typing import Protocol, runtime_checkable

from silverfish_core.ports.types import ConversionResult


@runtime_checkable
class Converter(Protocol):
    """Convert a book file from one format to another."""

    def convert(
        self,
        input_path: str,
        output_path: str,
        *,
        opf: bytes | None = None,
        cover: bytes | None = None,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> ConversionResult:
        """Convert *input_path* into *output_path*.

        *opf* and *cover*, when given, are embedded into the output. *on_progress*
        receives ``(fraction, message)`` as conversion proceeds, where *message*
        describes the current step.
        """
        ...
