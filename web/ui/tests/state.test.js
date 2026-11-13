/// <reference lib="deno.ns" />
// Actions and the page's state (S12.19): an action off says why and does nothing; empty, a
// pill and a notice of attention, each one component. No DOM: the elements are read as made.
import { equal, truthy } from './assert.js';

const g = /** @type {any} */ (globalThis);
g.document = { querySelector: () => null, getElementById: () => null };
const { Action, Attention, Empty, StatePill } = await import('../components/state.js');

/** Every element in the tree, depth first. @param {any} v @returns {any[]} */
function all(v) {
  if (v == null || typeof v !== 'object') return [];
  if (Array.isArray(v)) return v.flatMap(all);
  return [v, ...all(v.props?.children)];
}

Deno.test('an action open now is a plain button that does what it does', () => {
  let pressed = 0;
  const [b] = all(Action({ class: 'btn sm', onClick: () => pressed++, children: 'Go' }));
  equal([b.type, b.props.class, b.props['aria-disabled'], b.props['data-tip']], [
    'button',
    'btn sm',
    undefined,
    undefined,
  ]);
  b.props.onClick();
  equal(pressed, 1);
  equal(all(Action({ type: 'submit', children: 'Save' }))[0].props.type, 'submit');
});

Deno.test('one off is shown, says why, reaches the keyboard and does nothing', () => {
  let pressed = 0;
  let prevented = false;
  const [b] = all(Action({
    why: 'Shared with you to read',
    type: 'submit',
    onClick: () => pressed++,
    children: 'Delete',
  }));
  equal([b.type, b.props.type, b.props['aria-disabled']], ['button', 'button', 'true']);
  equal([b.props['data-tip'], b.props['aria-description']], [
    'Shared with you to read',
    'Shared with you to read',
  ]);
  equal(b.props.disabled, undefined, 'never disabled: it stays in reach of Tab');
  // Its reason is its tooltip, over any tooltip of its own (an icon's name).
  const [i] = all(Action({ why: 'Only its owner shares it', 'data-tip': 'Share', children: 'S' }));
  equal(i.props['data-tip'], 'Only its owner shares it');
  b.props.onClick({ preventDefault: () => (prevented = true) });
  equal([pressed, prevented], [0, true]);
});

Deno.test('empty is a line, with the action that makes the first one', () => {
  const tree = all(Empty({ children: 'No saved plans', action: 'ACTION' }));
  equal(tree[0].props.class, 'empty');
  truthy(tree.some((x) => x.props?.class === 'empty-action'));
  equal(
    all(Empty({ children: 'Nothing yet' })).some((x) => x.props?.class === 'empty-action'),
    false,
  );
});

Deno.test('a pill says why on hover and focus; attention is a line and its actions', () => {
  const [p] = all(StatePill({ children: '3 uncategorised', why: 'Select rows…', tone: 'warn' }));
  equal([p.props.class, p.props.tabindex, p.props['data-tip']], ['pill warn', '0', 'Select rows…']);
  equal(all(StatePill({ children: 'x', why: 'y' }))[0].props.class, 'pill');
  const [n] = all(Attention({ children: 'Statement overdue', actions: 'A' }));
  equal([n.props.class, n.props.role], ['notice attention warn', 'status']);
  truthy(all(n).some((x) => x.props?.class === 'attention-actions'));
  equal(all(Attention({ children: 'x', tone: 'bad' }))[0].props.class, 'notice attention bad');
  equal(
    all(Attention({ children: 'x' })).some((x) => x.props?.class === 'attention-actions'),
    false,
  );
});
