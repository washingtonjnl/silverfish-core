"""Export the API's OpenAPI document to a versioned file.

The OpenAPI spec is the source of truth for every generated SDK, so it is
committed (``packages/sdk-node/openapi.json``) rather than produced on the fly:
that gives a reviewable diff whenever the contract changes and lets any
generator (Hey API for TypeScript now, openapi-generator for other languages
later) read the same file.

Run it from a clean environment so app settings don't leak into the build:
    python scripts/export_openapi.py
"""

import json
import os
import sys
import tempfile
from pathlib import Path

_OUTPUT = Path(__file__).resolve().parent.parent / "packages" / "sdk-node" / "openapi.json"


def main() -> int:
    # Build the app from a clean cwd/env so it never reads a developer .env.local
    # (the spec must be deterministic, independent of local config).
    for key in [k for k in os.environ if k.startswith("SILVERFISH_")]:
        del os.environ[key]
    os.chdir(tempfile.mkdtemp())

    from silverfish_api.app import create_app

    spec = create_app().openapi()
    # The version comes straight from __version__ (git-tag dynamic versioning):
    # on a clean checkout at a tag it is the clean release (e.g. "0.12.0"); the
    # release CI regenerates this file there, so the committed spec carries the
    # real tag version with no string munging. A local run shows the dev version.
    _OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    # Stable formatting (sorted keys, trailing newline) so diffs are minimal.
    _OUTPUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {_OUTPUT} (version {spec['info']['version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
