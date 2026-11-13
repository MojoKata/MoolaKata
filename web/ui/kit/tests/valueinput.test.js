/// <reference lib="deno.ns" />
// ValueInput (R3.11): the controls it makes for a field's special values, as elements. No DOM:
// the modules that read the page at load see an empty one.
import { equal } from './assert.js';

const g = /** @type {any} */ (globalThis);
g.document = { querySelector: () => null, getElementById: () => null };
const { ValueInput, CountInput, typedHandlers } = await import('../fields.js');

/** Every element in the tree, depth first. @param {any} v @returns {any[]} */
function all(v) {
  if (v == null || typeof v !== 'object') return [];
  if (Array.isArray(v)) return v.flatMap(all);
  return [v, ...all(v.props?.children)];
}

/** What the field shows: the input's props and each button's name and state. @param {any} p */
function drawn(p) {
  const got = /** @type {string[]} */ ([]);
  const tree = all(ValueInput({ onInput: (/** @type {string} */ v) => got.push(v), ...p }));
  const input = tree.find((x) => typeof x.type === 'function' && 'onInput' in x.props).props;
  const buttons = tree.filter((x) => x.type === 'button').map((b) => ({
    name: b.props['aria-label'],
    tip: b.props['data-tip'],
    off: !!b.props.disabled,
    press: () => b.props.onClick(),
  }));
  return { input, buttons, got };
}

Deno.test('clear and reset sit in the field, each while it would change something', () => {
  const reset = { value: '30', label: '30 days' };
  const d = drawn({ value: '45', clear: true, reset });
  equal(d.buttons.map((b) => b.name), ['Clear', 'Use the default: 30 days']);
  equal(d.buttons.map((b) => b.tip), ['Clear', 'Use the default: 30 days']);
  d.buttons.forEach((b) => b.press());
  equal(d.got, ['', '30']);
  equal(drawn({ value: '30', clear: true, reset }).buttons.map((b) => b.name), ['Clear']);
  equal(drawn({ value: '', clear: true, reset }).buttons.map((b) => b.name), [
    'Use the default: 30 days',
  ]);
});

Deno.test('an amount has Min and Max, named with their values, greyed while held', () => {
  const money = (/** @type {number} */ n) => `$${n.toFixed(2)}`;
  const d = drawn({ value: '1250', min: 10, max: 1250, format: money });
  equal(d.buttons.map((b) => [b.name, b.off]), [['Min: $10.00', false], ['Max: $1250.00', true]]);
  d.buttons[0].press();
  equal(d.got, ['10']);
  equal(drawn({ value: '9', min: 10, max: 1250 }).input.bad, undefined, 'marks are not its own');
});

Deno.test('a count is a typed count from 1, with All only', () => {
  const tree = all(CountInput({ value: '1', onInput: () => {}, max: 2, noun: 'contracts' }));
  const field = tree.find((x) => x.props?.noun === 'contracts');
  equal([field.props.kind, field.props.min, field.props.max], ['count', 1, 2]);
  const d = drawn(field.props);
  equal(d.buttons.map((b) => b.name), ['All: 2 contracts']);
  equal(drawn({ ...field.props, value: '2' }).buttons[0].off, true);
});

Deno.test('another value is a button after the bounds', () => {
  const fill = [{ text: 'Last year', value: '4200', label: "Use last year's: 4,200.00" }];
  const d = drawn({ value: '', max: 5000, fill });
  equal(d.buttons.map((b) => b.name), ['Max: 5000', "Use last year's: 4,200.00"]);
  equal(drawn({ value: '', fill }).input.inputmode, undefined);
});

/** A typed input's handlers over a fake field, and what they did. @param {any} p */
function typed(p) {
  const did = {
    marks: /** @type {(string | null)[]} */ ([]),
    got: /** @type {string[]} */ ([]),
    commits: /** @type {[string, boolean][]} */ ([]),
  };
  const h = typedHandlers({
    kind: 'money',
    bounds: { min: 0 },
    mark: null,
    onMark: (m) => did.marks.push(m),
    onInput: (v) => did.got.push(v),
    onCommit: (v, ok) => did.commits.push([v, ok]),
    ...p,
  });
  const el = {
    value: '12',
    selectionStart: 2,
    selectionEnd: 2,
    attrs: /** @type {{ [k: string]: string }} */ ({}),
    setAttribute(/** @type {string} */ k, /** @type {string} */ v) {
      this.attrs[k] = v;
    },
    closest() {
      return this;
    },
    getAttribute(/** @type {string} */ k) {
      return this.attrs[k];
    },
    getBoundingClientRect: () => ({ left: 0, bottom: 0 }),
    setRangeText(/** @type {string} */ t, /** @type {number} */ a, /** @type {number} */ b) {
      this.value = this.value.slice(0, a) + t + this.value.slice(b);
    },
  };
  let stopped = false;
  const ev = (/** @type {any} */ x) => ({
    currentTarget: el,
    target: el,
    preventDefault: () => (stopped = true),
    ...x,
  });
  return { h, el, did, ev, stopped: () => stopped };
}

Deno.test('a key outside the kind is refused and marked with what it takes', () => {
  const t = typed({});
  t.h.onBeforeInput(t.ev({ inputType: 'insertText', data: 'x' }));
  equal([t.stopped(), t.did.marks, t.el.attrs['data-tip']], [
    true,
    ['Digits and . only.'],
    'Digits and . only.',
  ]);
  const u = typed({});
  u.h.onBeforeInput(u.ev({ inputType: 'insertText', data: '5' }));
  u.h.onBeforeInput(u.ev({ inputType: 'deleteContentBackward', data: null }));
  equal([u.stopped(), u.did.marks], [false, []], 'its own characters and deletions pass');
  const v = typed({ kind: 'text' });
  v.h.onBeforeInput(v.ev({ inputType: 'insertText', data: '¿' }));
  equal(v.stopped(), false, 'text takes anything');
});

Deno.test('a drop is refused where a kind has its characters, taken as text', () => {
  const t = typed({});
  t.h.onDrop(t.ev({}));
  equal(t.stopped(), true);
  const u = typed({ kind: 'text' });
  u.h.onDrop(u.ev({}));
  equal(u.stopped(), false);
});

Deno.test('text put in whole is cleaned as a paste is, or refused whole', () => {
  const t = typed({});
  t.el.value = '';
  t.el.selectionStart = t.el.selectionEnd = 0;
  t.h.onBeforeInput(t.ev({ inputType: 'insertText', data: '$300,000' }));
  equal([t.stopped(), t.el.value, t.did.got], [true, '300000', ['300000']]);
  const u = typed({});
  u.h.onBeforeInput(u.ev({ inputType: 'insertText', data: 'twelve' }));
  equal([u.stopped(), u.el.value, u.did.marks], [true, '12', ['Digits and . only.']]);
  const v = typed({});
  v.h.onBeforeInput(v.ev({ inputType: 'insertText', data: '1.5' }));
  equal([v.stopped(), v.did.got], [false, []], 'text of its own goes in as typed');
});

Deno.test('a paste is cleaned into the field, or refused whole', () => {
  const t = typed({});
  t.h.onPaste(t.ev({ clipboardData: { getData: () => '$1,000' } }));
  equal([t.stopped(), t.el.value, t.did.got, t.did.marks], [true, '121000', ['121000'], [null]]);
  const u = typed({});
  u.h.onPaste(u.ev({ clipboardData: { getData: () => '12 USD' } }));
  equal([u.el.value, u.did.got, u.did.marks], ['12', [], ['Digits and . only.']]);
  const v = typed({ kind: 'text' });
  v.h.onPaste(v.ev({ clipboardData: { getData: () => 'x' } }));
  equal(v.stopped(), false, 'text pastes as the browser does');
});

Deno.test('checked when left, at Enter and at Save; any change clears the mark', () => {
  const t = typed({});
  t.h.onInput('1.2.3');
  equal(t.did.marks, [null], 'not checked while typed');
  t.el.value = '1.2.3';
  t.h.onBlur(t.ev({}));
  equal(t.did.marks.at(-1), 'Type an amount, such as 1234.50.');
  equal(t.did.commits, [['1.2.3', false]]);
  t.h.onInput('1.2');
  equal(t.did.marks.at(-1), null);
  t.el.value = '1.25';
  t.h.onKeyDown(t.ev({ key: 'Enter' }));
  equal([t.did.marks.at(-1), t.did.commits.at(-1)], [null, ['1.25', true]]);
  t.h.onKeyDown(t.ev({ key: 'a' }));
  equal(t.did.commits.length, 2, 'only Enter commits');
  t.el.value = '-1';
  const save = { detail: { marked: false } };
  t.h['onmk-check'](t.ev(save));
  equal([save.detail.marked, t.did.marks.at(-1)], [true, '0 or more.']);
  t.el.value = '';
  const blank = { detail: { marked: false } };
  t.h['onmk-check'](t.ev(blank));
  equal(blank.detail.marked, false, "a blank is the server's to refuse");
});
