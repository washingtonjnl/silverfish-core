# Silverfish

Open-source core for an ebook library. Silverfish speaks the **Calibre dialect**
(how books are organised on disk, how sort keys and paths are computed, how
metadata is extracted/injected, how formats are converted) but is its own
platform — it does not inherit any Calibre application or UI.

This repository (`silverfish-core`) is the open-source heart of the project:

- **`packages/core`** — the library: domain rules, ports (interfaces), services
  (use cases) and reference adapters. No web, no concrete persistence at its
  boundary; consumers plug adapters in.
- **`packages/api`** — a thin FastAPI layer exposing the core over HTTP and
  generating the OpenAPI contract used to produce client SDKs.
- *(later)* **`packages/sdk-node`** — a TypeScript client generated from the
  OpenAPI contract.

## Architecture

Hexagonal (ports & adapters). The core defines *rules* and *interfaces*; each
adapter plugs in a concrete *implementation* (a Calibre or native repository,
local/S3/Drive storage, an SMTP mailer, …). The logic runs once, in Python,
behind the REST API; consumers in any language talk HTTP via a generated SDK.

## What it does

- **Library management** — list, search, fetch, upload, edit and delete books;
  download a book's formats and cover. Metadata is extracted from uploaded files
  (EPUB/PDF/…), and book files are laid out the Calibre way (`Author/Title (id)/`).
- **Two library modes** (`SILVERFISH_LIBRARY_MODE`):
  - `standalone` (default) — Silverfish owns the database (its own neutral
    schema, SQLite or Postgres) and assigns short, time-ordered ids.
  - `calibre` — Silverfish reads an existing Calibre `metadata.db`, acting as an
    API over a Calibre library you already have.
- **Two independent databases** — the book library and a separate system store
  (config, job state, export tokens), each a SQLite path or a Postgres URL.
- **Pluggable storage** for book files — local disk, S3 (or S3-compatible like
  MinIO/R2), or Google Drive.
- **Conversion & metadata** via the Calibre binaries (`ebook-convert`,
  `ebook-meta`) when present; EPUB metadata is handled in pure Python.
- **Send to e-reader** — email a book (e.g. to a Kindle) over SMTP.
- **Export to Calibre** — snapshot the library into a real Calibre folder, zipped
  and delivered as a time-limited download link.
- **Background jobs** — slow work (convert/send/export) runs asynchronously; poll
  `GET /jobs/{id}` or stream progress over SSE. Job state is persisted, so it
  survives a restart.

## Configuration

All configuration is via environment variables (prefix `SILVERFISH_`), read from
the real environment, then `.env.local`, then `.env`. Copy `.env.example` to
`.env.local` and adjust — it documents every option. Secrets (SMTP password,
S3/Drive credentials) belong in `.env.local`, which is gitignored.

The defaults run out of the box: standalone mode with a local SQLite library and
local file storage under `./silverfish-library`. SMTP, cloud storage and the
Calibre binaries are optional and unlock the corresponding features when set.

## Optional extras

Some backends are optional dependencies, kept out of the default install:

```bash
uv sync --all-packages --extra postgres   # Postgres driver (psycopg)
uv sync --all-packages --extra s3         # S3 storage (boto3)
uv sync --all-packages --extra gdrive     # Google Drive storage
```

Conversion and non-EPUB metadata also need the **Calibre binaries**
(`ebook-convert`, `ebook-meta`, `calibredb`) on the system — install Calibre and,
if needed, point `SILVERFISH_CALIBRE_BIN_DIR` at them. Without them, the library
still reads/writes, uploads, searches and sends EPUB; only conversion and export
require Calibre.

## Development

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages      # install workspace + dev tooling
uv run pytest               # tests
uv run mypy                 # strict type-check
uv run ruff check           # lint
uv run ruff format          # format
uv run pre-commit install   # enable the local commit gate
```

Run the API locally:

```bash
uv run uvicorn silverfish_api.app:create_app --factory --reload
# OpenAPI docs at http://127.0.0.1:8000/docs
```

### Non-negotiable project rules

TDD (tests before implementation), full-flow test coverage, lint always,
**strict typing with zero `any`**, a branch + PR per change, and a
security-first (anti-hacking) mindset throughout.
