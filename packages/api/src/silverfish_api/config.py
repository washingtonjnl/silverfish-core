"""API configuration, sourced from the environment.

The library directory is the one knob that matters for the reference API:
``SILVERFISH_LIBRARY_DIR`` points at a Calibre library folder (containing
``metadata.db``). If unset, a local default directory is used so the API runs
out of the box for testing.
"""

import os
from dataclasses import dataclass
from pathlib import Path

ENV_LIBRARY_DIR = "SILVERFISH_LIBRARY_DIR"
DEFAULT_LIBRARY_DIR = "silverfish-library"


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved API settings."""

    library_dir: Path

    @property
    def metadata_db(self) -> Path:
        return self.library_dir / "metadata.db"


def load_settings() -> Settings:
    """Build settings from the environment, applying the local default."""
    raw = os.environ.get(ENV_LIBRARY_DIR, "").strip()
    library_dir = Path(raw) if raw else Path(DEFAULT_LIBRARY_DIR)
    return Settings(library_dir=library_dir.resolve())
