/// <reference lib="deno.ns" />
// The ui-kit stands on its own (requirements S17.3.10.3): a module in kit/, its tests and its
// pages included, imports only kit/ and the vendored libraries.
import { equal } from './assert.js';

const KIT = new URL('../', import.meta.url);
const VENDORED = new Set([
  'preact',
  'preact/hooks',
  'htm',
  '@preact/signals',
  '@preact/signals-core',
  // The note editor's (S12.18.15).
  'prosemirror-model',
  'prosemirror-state',
  'prosemirror-view',
  'prosemirror-transform',
  'prosemirror-commands',
  'prosemirror-keymap',
  'prosemirror-history',
  'prosemirror-inputrules',
  'prosemirror-schema-list',
]);

/** Every .js file under a directory. @param {URL} dir @returns {URL[]} */
function scripts(dir) {
  const out = [];
  for (const e of Deno.readDirSync(dir)) {
    const u = new URL(e.name + (e.isDirectory ? '/' : ''), dir);
    if (e.isDirectory) out.push(...scripts(u));
    else if (e.name.endsWith('.js')) out.push(u);
  }
  return out;
}

Deno.test('a kit module imports only the kit and the vendored libraries', () => {
  const outside = [];
  for (const file of scripts(KIT)) {
    const src = Deno.readTextFileSync(file);
    const specs = [
      ...src.matchAll(/(?:^|\n)\s*import\s[^'"]*?from\s*['"]([^'"]+)['"]/g),
      ...src.matchAll(/(?:^|\n)\s*import\s*['"]([^'"]+)['"]/g),
      ...src.matchAll(/\bimport\(\s*['"]([^'"]+)['"]\s*\)/g),
    ].map((m) => m[1]);
    for (const spec of specs) {
      const inside = spec.startsWith('.')
        ? new URL(spec, file).href.startsWith(KIT.href)
        : VENDORED.has(spec);
      if (!inside) outside.push(`${file.href.slice(KIT.href.length)}: ${spec}`);
    }
  }
  equal(outside, []);
});
