/// <reference lib="deno.ns" />
// ValueInput (R3.11): the controls it makes for a field's special values, as elements. No DOM:
// the modules that read the page at load see an empty one.
import { equal } from './assert.js';

const g = /** @type {any} */ (globalThis);
g.document = { querySelector: () => null, getElementById: () => null };
const { ValueInput, CountInput } = await import('../components/fields.js');

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
  equal(d.input.inputmode, 'decimal');
  equal(drawn({ value: '9', min: 10, max: 1250 }).input.bad, true);
  equal(drawn({ value: '12', min: 10, max: 1250 }).input.bad, false);
});

Deno.test('a count has All only, and marks what is not whole', () => {
  const tree = all(CountInput({ value: '1.5', onInput: () => {}, max: 2, noun: 'contracts' }));
  const field = tree.find((x) => x.props?.noun === 'contracts');
  const d = drawn(field.props);
  equal(d.buttons.map((b) => b.name), ['All: 2 contracts']);
  equal([d.input.bad, d.input.inputmode], [true, 'numeric']);
  equal(drawn({ ...field.props, value: '2' }).buttons[0].off, true);
});

Deno.test('another value is a button after the bounds', () => {
  const fill = [{ text: 'Last year', value: '4200', label: "Use last year's: 4,200.00" }];
  const d = drawn({ value: '', max: 5000, fill });
  equal(d.buttons.map((b) => b.name), ['Max: 5000', "Use last year's: 4,200.00"]);
  equal(drawn({ value: '', fill }).input.inputmode, undefined);
});
