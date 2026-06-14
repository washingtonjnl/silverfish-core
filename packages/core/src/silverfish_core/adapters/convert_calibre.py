"""Format conversion via the native ``ebook-convert`` binary.

Builds an argv (never a shell), runs it through the safe runner, and parses the
percentage output into progress. Optional OPF/cover bytes are written to temp
files and embedded with ``--from-opf``/``--cover``. The output format is derived
from the output path's extension.
"""

import re
import tempfile
from collections.abc import Callable
from pathlib import Path

from silverfish_core.adapters.calibre_binaries import ProcessRunner, SubprocessRunner
from silverfish_core.ports.types import ConversionResult

# Calibre prints lines like "12% Converting input to HTML...". Capture the
# percentage and the descriptive message that follows it.
_PROGRESS_RE = re.compile(r"(\d+)%\s*(.*)")


class CalibreConverter:
    """Convert book files by invoking ``ebook-convert``."""

    def __init__(self, *, ebook_convert: Path, runner: ProcessRunner | None = None) -> None:
        self._ebook_convert = ebook_convert
        self._runner: ProcessRunner = runner or SubprocessRunner()

    def convert(
        self,
        input_path: str,
        output_path: str,
        *,
        opf: bytes | None = None,
        cover: bytes | None = None,
        on_progress: Callable[[float, str], None] | None = None,
    ) -> ConversionResult:
        output_format = Path(output_path).suffix.lstrip(".").upper()
        tmp_paths: list[Path] = []
        try:
            argv = [str(self._ebook_convert), input_path, output_path]
            if opf is not None:
                opf_path = self._spill(opf, ".opf")
                tmp_paths.append(opf_path)
                argv += ["--from-opf", str(opf_path)]
            if cover is not None:
                cover_path = self._spill(cover, ".jpg")
                tmp_paths.append(cover_path)
                argv += ["--cover", str(cover_path)]

            # Stream stdout line-by-line so progress is reported live, not only
            # after ebook-convert finishes.
            on_line = self._progress_line_handler(on_progress)
            result = self._runner.run(argv, on_line=on_line)
        finally:
            for path in tmp_paths:
                path.unlink(missing_ok=True)

        if result.returncode != 0:
            return ConversionResult(
                ok=False,
                output_format=output_format,
                error=self._clean_error(result.stderr),
            )
        return ConversionResult(ok=True, output_format=output_format, error=None)

    def _spill(self, data: bytes, suffix: str) -> Path:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(data)
            return Path(tmp.name)

    def _progress_line_handler(
        self, on_progress: Callable[[float, str], None] | None
    ) -> Callable[[str], None] | None:
        if on_progress is None:
            return None

        def handle(line: str) -> None:
            match = _PROGRESS_RE.search(line)
            if match:
                fraction = int(match.group(1)) / 100.0
                message = match.group(2).strip()
                on_progress(fraction, message)

        return handle

    def _clean_error(self, stderr: str) -> str:
        """Drop Python traceback noise, keeping the meaningful Calibre lines."""
        lines = [
            line
            for line in stderr.splitlines()
            if line.strip() and not line.startswith("Traceback") and not line.startswith("  File")
        ]
        return "\n".join(lines) if lines else "Conversion failed"
