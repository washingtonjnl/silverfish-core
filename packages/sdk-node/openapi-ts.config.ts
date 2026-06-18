import { defineConfig } from '@hey-api/openapi-ts';

// Generates the typed client from the committed OpenAPI contract. The contract
// (openapi.json) is the source of truth — regenerated on release from a clean
// tag build, so it always carries the real release version.
export default defineConfig({
  input: './openapi.json',
  output: {
    path: './src',
  },
  plugins: [
    '@hey-api/client-fetch',
    {
      name: '@hey-api/sdk',
      // Tree-shakeable function-per-operation; method names come from the clean
      // snake_case operationIds we set in the API.
      operations: { strategy: 'single' },
    },
  ],
});
