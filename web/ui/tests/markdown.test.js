/// <reference lib="deno.ns" />
// A guide's Markdown (requirements S12.7.4): an image the help pane has no screenshot for is left
// out (S12.7.5), never drawn broken.
import { equal } from '../kit/tests/assert.js';

const g = /** @type {any} */ (globalThis);
g.document ??= { querySelector: () => null, getElementById: () => null };
const { render } = await import('../components/markdown.js');

/** Every element in the tree, depth first. @param {any} v @returns {any[]} */
function all(v) {
  if (v == null || typeof v !== 'object') return [];
  if (Array.isArray(v)) return v.flatMap(all);
  return [v, ...all(v.props?.children)];
}

const GUIDE = '# Accounts\n\nEvery account.\n\n![Accounts](shots/accounts.png)\n';
const none = new Map();

Deno.test('an image is drawn where it points', () => {
  const imgs = all(render(GUIDE, (src) => `/guides/${src}`, none, none))
    .filter((e) => e.type === 'img');
  equal(imgs.map((i) => [i.props.src, i.props.alt]), [['/guides/shots/accounts.png', 'Accounts']]);
});

Deno.test('an image with nowhere to point is left out, and the words stay', () => {
  const tree = all(render(GUIDE, () => null, none, none));
  equal(tree.filter((e) => e.type === 'img').length, 0);
  equal(
    tree.some((e) =>
      e.props?.children === 'Every account.' ||
      (Array.isArray(e.props?.children) && e.props.children.includes('Every account.'))
    ),
    true,
  );
});

Deno.test('an image that fails to load is hidden, not drawn broken', () => {
  const [img] = all(render(GUIDE, (src) => `/guides/${src}`, none, none))
    .filter((e) => e.type === 'img');
  const shown = { hidden: false };
  img.props.onError({ currentTarget: shown });
  equal(shown.hidden, true);
});
