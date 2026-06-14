"""Discovery and safe invocation of the Calibre command-line binaries.

``ebook-convert`` and ``ebook-meta`` are native executables and a system
dependency — not Python packages. They are located via an explicit directory
(from config) or OS autodetection, and always run as an argv list (never a
shell) so a filename or metadata value can never be interpreted as a command.
"""

import os
import platform
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

EBOOK_CONVERT = "ebook-convert"
EBOOK_META = "ebook-meta"

# Default locations Calibre installs into, per OS. Mirrors calibre-web's
# autodetection (cps/config_sql.py).
_DEFAULT_SEARCH_PATHS: dict[str, tuple[Path, ...]] = {
    "Darwin": (Path("/Applications/calibre.app/Contents/MacOS"),),
    "Linux": (Path("/opt/calibre"), Path("/usr/bin"), Path("/usr/local/bin")),
    "Windows": (
        Path(r"C:\Program Files\Calibre2"),
        Path(r"C:\Program Files (x86)\Calibre2"),
    ),
}

# Cap on how long a Calibre command may run before we give up.
DEFAULT_TIMEOUT_SECONDS = 600.0


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Outcome of a subprocess run."""

    returncode: int
    stdout: str
    stderr: str


@runtime_checkable
class ProcessRunner(Protocol):
    """Runs an argv list and returns its result. Lets adapters depend on the
    capability, not the concrete runner (so tests can substitute a fake).
    """

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = ...,
        env: dict[str, str] | None = ...,
        on_line: Callable[[str], None] | None = ...,
    ) -> ProcessResult: ...


class SubprocessRunner:
    """Run external commands safely: argv lists only, never a shell."""

    def run(
        self,
        argv: list[str],
        *,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        env: dict[str, str] | None = None,
        on_line: Callable[[str], None] | None = None,
    ) -> ProcessResult:
        """Run *argv* and return its result.

        ``shell`` is never used, so list elements are passed verbatim and shell
        metacharacters in (e.g.) a filename are inert. When *on_line* is given,
        stdout is read line-by-line as the process runs and each line is passed
        to it (live progress); otherwise output is captured at once. Raises
        ``TimeoutError`` on timeout and ``FileNotFoundError`` if the executable
        does not exist.
        """
        if on_line is None:
            return self._run_buffered(argv, timeout=timeout, env=env)
        return self._run_streaming(argv, timeout=timeout, env=env, on_line=on_line)

    def _run_buffered(
        self, argv: list[str], *, timeout: float, env: dict[str, str] | None
    ) -> ProcessResult:
        try:
            completed = subprocess.run(  # noqa: S603 - argv list, shell=False, no user-controlled executable
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            msg = f"Command timed out after {timeout}s: {argv[0]}"
            raise TimeoutError(msg) from exc
        return ProcessResult(
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def _run_streaming(
        self,
        argv: list[str],
        *,
        timeout: float,
        env: dict[str, str] | None,
        on_line: Callable[[str], None],
    ) -> ProcessResult:
        stdout_lines: list[str] = []
        process = subprocess.Popen(  # noqa: S603 - argv list, shell=False, no user-controlled executable
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            env=env,
        )
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    stdout_lines.append(line)
                    on_line(line)
            _, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            msg = f"Command timed out after {timeout}s: {argv[0]}"
            raise TimeoutError(msg) from exc
        return ProcessResult(
            returncode=process.returncode,
            stdout="".join(stdout_lines),
            stderr=stderr or "",
        )


@dataclass(frozen=True, slots=True)
class BinaryHealth:
    """Whether each Calibre binary was found and is executable."""

    convert_available: bool
    metadata_available: bool


class CalibreBinaries:
    """Locate the Calibre binaries and report their availability."""

    def __init__(
        self,
        *,
        bin_dir: Path | None = None,
        search_paths: tuple[Path, ...] | None = None,
        runner: SubprocessRunner | None = None,
    ) -> None:
        self._runner = runner or SubprocessRunner()
        candidates = (bin_dir,) if bin_dir is not None else self._default_search_paths(search_paths)
        self._ebook_convert = self._find(EBOOK_CONVERT, candidates)
        self._ebook_meta = self._find(EBOOK_META, candidates)

    @property
    def ebook_convert(self) -> Path | None:
        return self._ebook_convert

    @property
    def ebook_meta(self) -> Path | None:
        return self._ebook_meta

    def health(self) -> BinaryHealth:
        return BinaryHealth(
            convert_available=self._ebook_convert is not None,
            metadata_available=self._ebook_meta is not None,
        )

    def _default_search_paths(self, override: tuple[Path, ...] | None) -> tuple[Path | None, ...]:
        if override is not None:
            return override
        return _DEFAULT_SEARCH_PATHS.get(platform.system(), ())

    def _find(self, name: str, candidates: tuple[Path | None, ...]) -> Path | None:
        for directory in candidates:
            if directory is None:
                continue
            path = directory / name
            if path.is_file() and os.access(path, os.X_OK):
                return path
        return None
