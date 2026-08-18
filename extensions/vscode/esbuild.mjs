// Bundle the extension into one file.
//
// VS Code loads `main` and everything it requires at activation; nine loose
// modules are nine reads and nine resolutions, and the `.vsix` carries the
// tree. esbuild resolves it once, at build time.
//
// `vscode` is external because the editor injects it at runtime — bundling it
// is impossible and asking is a build error, which is the useful behaviour.
import { context, build } from 'esbuild';

const watch = process.argv.includes('--watch');
const options = {
  entryPoints: ['src/extension.ts'],
  bundle: true,
  outfile: 'out/extension.js',
  external: ['vscode'],
  format: 'cjs',
  platform: 'node',
  // The floor VS Code 1.85 ships; anything newer risks syntax it cannot parse.
  target: 'node18',
  sourcemap: !watch ? false : 'inline',
  minify: !watch,
  logLevel: 'info',
};

if (watch) {
  const ctx = await context(options);
  await ctx.watch();
} else {
  await build(options);
}
