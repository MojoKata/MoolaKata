/// <reference lib="deno.ns" />
// The pages' policy (requirements S17.3.3): the import map is let in by its hash alone, so the
// hash in the page's CSP is the map's as the page holds it now (a reformatted map changes it).
import { equal } from './assert.js';

Deno.test("the pages' CSP lets in their import map by its hash", async () => {
  const page = await Deno.readTextFile(new URL('../pages/index.html', import.meta.url));
  const map = /<script type="importmap">([\s\S]*?)<\/script>/.exec(page)?.[1] ?? '';
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(map));
  const hash = btoa(String.fromCharCode(...new Uint8Array(digest)));
  const policy = /<meta http-equiv="Content-Security-Policy"\s+content="([^"]*)"/.exec(page)?.[1];
  equal(policy?.match(/'sha256-([^']+)'/)?.[1], hash);
});
