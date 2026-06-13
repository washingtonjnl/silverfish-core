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
adapter plugs in a concrete *implementation* (SQLite-Calibre or Postgres
repository, local disk or cloud storage, SMTP or a managed mailer, a Z-Library
data source, …). The logic runs once, in Python, behind the REST API; consumers
in any language talk HTTP via a generated SDK.

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
