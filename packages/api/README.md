# silverfish-api

Thin FastAPI layer that exposes `silverfish-core` over HTTP and generates the
OpenAPI contract used to produce client SDKs (the first being Node/TypeScript).

It holds no domain logic — every route translates HTTP to/from a core service.
The quality of the Pydantic schemas here directly determines the quality of the
generated OpenAPI and therefore the SDKs, so they are treated as a first-class
contract.

```bash
uv run uvicorn silverfish_api.app:create_app --factory --reload
```
