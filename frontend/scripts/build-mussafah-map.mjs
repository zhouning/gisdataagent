import { build } from 'esbuild';

await build({
  entryPoints: ['mussafah/map.js'],
  outfile: 'dist/assets/mussafah-map.js',
  bundle: true,
  minify: true,
  format: 'iife',
  target: ['es2020'],
  loader: { '.png': 'dataurl' },
});
