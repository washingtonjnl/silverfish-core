# @silverfish-app/sdk

Official TypeScript client for the [Silverfish](../../README.md) API, **generated
from its OpenAPI contract** — it is a typed HTTP client and nothing more (no
domain logic lives here; that runs once, in the Python core, behind the API).

The contract (`openapi.json`) is the source of truth: it is committed and the
client is regenerated from it, so the SDK always matches the API.

## Install

```bash
npm install @silverfish-app/sdk
# or: pnpm add @silverfish-app/sdk
```

## Usage

Create a client pointed at your Silverfish API, then call the typed methods:

```ts
import { Sdk } from '@silverfish-app/sdk';
import { createClient, createConfig } from '@silverfish-app/sdk/client';

const sdk = new Sdk({
  client: createClient(createConfig({ baseUrl: 'http://localhost:8000' })),
});

// List books (typed response).
const { data } = await sdk.listBooks({ query: { page: 1, page_size: 50 } });
for (const book of data!.items) {
  console.log(book.id, book.title);
}

// Get one book by its public id.
const { data: book } = await sdk.getBook({ path: { book_id: '8X2k' } });

// Start an export (async job) — the download link is emailed when ready.
const { data: job } = await sdk.startExport({ body: { to_email: 'me@example.com' } });
console.log(job!.status); // 'queued' | 'running' | 'done' | 'error'
```

Errors, request bodies and responses are fully typed per operation. By default
methods return `{ data, error }`; pass `throwOnError: true` to get the data
directly and have failures throw instead.

## Regenerating

The client is generated from the committed contract — the generated `src/` and
compiled `dist/` are build artifacts and are not committed.

```bash
pnpm install
pnpm run generate   # regenerate src/ from openapi.json
pnpm run build      # compile to dist/
```

`openapi.json` itself is produced from the API by
`scripts/export_openapi.py` (run at release from a clean tag build, so it carries
the real release version). Other languages can be generated from the same file
with [openapi-generator](https://openapi-generator.tech/).
