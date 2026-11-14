/// <reference lib="deno.ns" />
// The list under a box (requirements S12.18.12) and the tag box's rules: every key the list
// answers, closed and open; what matches; names split, added, refused; the box's own keys.
import { listAction, listKey, matching, nameKey } from '../listbox.js';
import { equal } from './assert.js';

// No DOM: the modules that read the page at load see an empty one.
const g = /** @type {any} */ (globalThis);
g.document ??= { querySelector: () => null, getElementById: () => null };
const { addNames, boxKey, splitNames, suggestions } = await import('../tags.js');

const closed = { open: false, active: -1 };
/** @param {number} active */
const open = (active) => ({ open: true, active });

Deno.test('a key as the list names it; one with Ctrl, Meta or an Alt chord is the box’s', () => {
  equal(
    [
      { key: 'ArrowDown' },
      { key: 'ArrowDown', altKey: true },
      { key: 'ArrowUp', altKey: true },
      { key: 'Home' },
      { key: 'Enter' },
      { key: 'Escape' },
      { key: 'Enter', ctrlKey: true },
      { key: 'ArrowDown', metaKey: true },
      { key: 'Home', altKey: true },
      { key: 'a' },
      { key: 'Tab' },
    ].map(listKey),
    [
      'ArrowDown',
      'Alt+ArrowDown',
      'Alt+ArrowUp',
      'Home',
      'Enter',
      'Escape',
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
    ],
  );
});

Deno.test('the arrows open the list and move round it', () => {
  const s = (/** @type {any} */ key, /** @type {any} */ st, n = 3) => listAction(key, st, n).state;
  equal(
    [
      s('ArrowDown', closed),
      s('ArrowDown', open(0)),
      s('ArrowDown', open(2)),
      s('ArrowUp', closed),
      s('ArrowUp', open(0)),
      s('ArrowUp', open(2)),
      s('ArrowDown', closed, 0),
      s('Alt+ArrowDown', closed),
      s('Alt+ArrowUp', open(1)),
    ],
    [open(0), open(1), open(0), open(2), open(2), open(1), open(-1), open(-1), closed],
  );
});

Deno.test('Home and End move the list while it is open, and are the caret’s while it isn’t', () => {
  equal(listAction('Home', open(2), 3), { state: open(0), prevent: true, stop: false, pick: -1 });
  equal(listAction('End', open(0), 3), { state: open(2), prevent: true, stop: false, pick: -1 });
  equal(listAction('Home', closed, 3), { state: closed, prevent: false, stop: false, pick: -1 });
  equal(listAction('End', open(-1), 0).prevent, false);
});

Deno.test('Enter picks the one reached; Escape closes and, open, goes no further', () => {
  equal(listAction('Enter', open(1), 3), { state: closed, prevent: true, stop: false, pick: 1 });
  equal(listAction('Enter', open(-1), 3).pick, -1);
  equal(listAction('Enter', closed, 3), { state: closed, prevent: true, stop: false, pick: -1 });
  equal(listAction('Enter', open(5), 3).pick, -1);
  equal(listAction('Escape', open(1), 3), { state: closed, prevent: true, stop: true, pick: -1 });
  equal(listAction('Escape', closed, 3).stop, false);
});

Deno.test('what matches, best first: the whole name, its start, a later word, then anywhere', () => {
  const names = ['woodworking', 'work trips', 'coffee', 'home office', 'work', 'Network fees'];
  const by = (/** @type {string} */ q) => matching(names, q, (x) => x);
  equal(by('work'), ['work', 'work trips', 'woodworking', 'Network fees']);
  equal(by('wo'), ['woodworking', 'work trips', 'work', 'Network fees']);
  equal(by('off'), ['home office', 'coffee']);
  equal(by(''), names);
  equal(by('zz'), []);
  equal(nameKey('  Café '), 'café');
});

Deno.test('names split at commas: those finished, and the rest still typed', () => {
  equal(splitNames('work'), { names: [], rest: 'work' });
  equal(splitNames('work, '), { names: ['work'], rest: '' });
  equal(splitNames('a, , b,  c'), { names: ['a', 'b'], rest: 'c' });
});

Deno.test('names added: an item there by its name, case aside; new ones; refused; once each', () => {
  const items = [{ key: 'T1', label: 'work' }, { key: 'T2', label: 'Coffee' }];
  equal(addNames([], items, ['WORK', 'coffee', 'travel', 'Travel', ' '], true), {
    keys: ['T1', 'T2'],
    made: ['travel'],
    refused: [],
  });
  equal(addNames(['T1'], items, ['work', 'gym'], false), {
    keys: ['T1'],
    made: [],
    refused: ['gym'],
  });
  // A key with no item (a new one this draft made) counts as its own name.
  equal(addNames(['road'], items, ['Road'], true), { keys: ['road'], made: [], refused: [] });
});

Deno.test('suggestions leave out the chosen, most used first while nothing is typed', () => {
  const items = [
    { key: 'a', label: 'gifts', uses: 2 },
    { key: 'b', label: 'work', uses: 40 },
    { key: 'c', label: 'coffee' },
    { key: 'd', label: 'work trips', uses: 5 },
  ];
  equal(suggestions(items, ['b'], '').map((i) => i.label), ['work trips', 'gifts', 'coffee']);
  equal(suggestions(items, [], 'wo').map((i) => i.label), ['work', 'work trips']);
});

Deno.test("the box's own keys: a comma, Backspace in an empty box, Enter", () => {
  const k = (/** @type {any} */ e, text = '', st = closed, n = 2) => boxKey(e, st, n, text);
  equal(k({ key: ',' })?.commit, true);
  equal(k({ key: ',', altKey: true }), undefined);
  equal(k({ key: 'Backspace' })?.removeLast, true);
  equal(k({ key: 'Backspace' }, 'wo'), undefined);
  equal(k({ key: 'Backspace', repeat: true }), undefined);
  equal(k({ key: 'Enter' }, 'gym')?.commit, true);
  equal(k({ key: 'Enter' }, 'gym', open(1))?.pick, 1);
  equal(k({ key: 'Escape' }, '', open(0))?.stop, true);
  equal(k({ key: 'ArrowDown' })?.state, open(0));
  equal(k({ key: 'x' }), undefined);
  equal(k({ key: 'Enter', ctrlKey: true }), undefined);
});
