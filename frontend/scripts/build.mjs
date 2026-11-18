// Production bundling uses esbuild directly to avoid Rollup's CommonJS parsing error
// observed with react-dom/client.js in the Fedora Docker build.
import { build } from 'esbuild';
import { mkdir, readFile, rm, writeFile, access } from 'node:fs/promises';
import { join } from 'node:path';

const output = 'dist';
const entry = join(output, 'assets');
await rm(output, { recursive: true, force: true });
await mkdir(entry, { recursive: true });

await build({
  entryPoints: ['src/main.jsx'],
  outdir: entry,
  entryNames: 'app',
  bundle: true,
  platform: 'browser',
  format: 'esm',
  target: ['es2020'],
  jsx: 'automatic',
  minify: true,
  legalComments: 'none',
  logLevel: 'info',
});

const html = await readFile('index.html', 'utf8');
const inputTag = '<script type="module" src="/src/main.jsx"></script>';
if (!html.includes(inputTag)) {
  throw new Error('index.html is missing the expected development entry point');
}
await Promise.all([
  access(join(entry, 'app.js')),
  access(join(entry, 'app.css')),
]);
await writeFile(
  join(output, 'index.html'),
  html.replace(inputTag,
    '<link rel="stylesheet" href="/assets/app.css" />\n    <script type="module" src="/assets/app.js"></script>'),
);
console.log('HomeLab OS production assets built successfully.');
