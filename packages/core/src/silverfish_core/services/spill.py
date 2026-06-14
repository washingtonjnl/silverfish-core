"""Write bytes to a temp file that keeps a meaningful name.

Path-based metadata tools (notably ``ebook-meta``) fall back to the *filename*
as the title when a file has no embedded metadata. If we spill uploads to a
random ``tmpXXXX`` name, that leaks as the title. Spilling to a file named after
the original upload means the fallback is a real name instead. The file lives in
a unique temp directory that is removed on exit.
"""

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from silverfish_core.domain.rules import valid_filename


@contextmanager
def spill_named(data: bytes, *, base_name: str, suffix: str) -> Iterator[Path]:
    """Write *data* to ``<tmpdir>/<base_name><suffix>`` and yield its path.

    *base_name* is sanitised for the filesystem; if it ends up empty, a neutral
    name is used. The temp directory (and file) are removed when the context
    exits, even on error.
    """
    safe_base = _safe_base(base_name)
    with tempfile.TemporaryDirectory(prefix="silverfish-") as tmp_dir:
        path = Path(tmp_dir) / f"{safe_base}{suffix}"
        path.write_bytes(data)
        yield path


def _safe_base(base_name: str) -> str:
    stripped = base_name.strip()
    if not stripped:
        return "upload"
    try:
        return valid_filename(stripped, chars=96)
    except ValueError:
        return "upload"
