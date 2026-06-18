import { defineConfig } from 'tsup';

// Bundle the generated client into a publishable library: ESM + CJS + type
// declarations, with import extensions resolved (the generated source uses
// extensionless imports, which plain tsc does not fix for Node ESM). Two entry
// points mirror the package exports: the SDK and the lower-level client.
export default defineConfig({
  entry: {
    index: 'src/index.ts',
    'client/index': 'src/client/index.ts',
  },
  format: ['esm', 'cjs'],
  dts: true,
  clean: true,
  sourcemap: true,
  treeshake: true,
});
