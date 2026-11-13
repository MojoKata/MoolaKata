/// <reference lib="deno.ns" />
// Numbers as they are typed (requirements S12.18.8): grouping as typed, the caret kept by its
// digits, a register's cents, and what a field holds for each way of holding a number.
import {
  groupText,
  padded,
  shift,
  shownText,
  textOf,
  typeNatural,
  typeRegister,
  ungroup,
  valueOf,
} from '../numbers.js';
import { equal } from './assert.js';

const money = /** @type {const} */ ({ places: 2, negative: true, entry: 'natural' });
const qty = /** @type {const} */ ({ places: null, negative: false, entry: 'natural' });
const till = /** @type {const} */ ({ places: 2, negative: true, entry: 'register' });

/** The text with `|` at the caret, as a test reads it. @param {{ text: string, start: number }} e */
const shown = (e) => e.text.slice(0, e.start) + '|' + e.text.slice(e.start);
/** An edit from text with `|` at the caret. @param {string} s */
const at = (s) => ({ text: s.replace('|', ''), start: s.indexOf('|'), end: s.indexOf('|') });
/** Each key typed in turn into `start`. @param {string} start @param {string} keys @param {any} way */
function typed(start, keys, way, type = typeNatural) {
  let e = at(start);
  for (const k of keys) e = type(e, k === '⌫' ? { back: true } : { insert: k }, way);
  return shown(e);
}

Deno.test('a number is grouped as far as it is typed', () => {
  equal(
    ['', '-', '1', '1234', '-1234.5', '1234.', '1234567.891', '0.5'].map(groupText),
    ['', '-', '1', '1,234', '-1,234.5', '1,234.', '1,234,567.891', '0.5'],
  );
  equal(ungroup('-1,234,567.89'), '-1234567.89');
});

Deno.test('typed as written, the digits grow to the left with their commas', () => {
  equal(typed('|', '1234567', qty), '1,234,567|');
  equal(typed('|', '1234.56', money), '1,234.56|');
  equal(typed('|', '.5', money), '0.5|');
  equal(typed('|', '007', qty), '7|');
});

Deno.test('the caret keeps as many digits to its right as before', () => {
  // Typed in the middle: the comma moves, the caret stays by its digit.
  equal(typed('12|34', '5', qty), '12,5|34');
  equal(typed('1,2|34', '9', qty), '12,9|34');
  // Deleted in the middle.
  equal(typed('12,3|45', '⌫', qty), '1,2|45');
  // A `.` typed before digits makes them the fraction, the caret after it.
  equal(typed('123|45', '.', money), '123.|45');
  // A second `.` is passed over.
  equal(typed('12.3|4', '.', money), '12.3|4');
});

Deno.test('Backspace just after a comma takes the digit before it', () => {
  equal(typed('1,|234', '⌫', qty), '|234');
  equal(typed('12,|345', '⌫', qty), '1,|345');
  equal(typed('1,234,|567', '⌫', qty), '123,|567');
});

Deno.test('a minus changes the sign where the field takes one, wherever the caret is', () => {
  equal(typed('1,2|34', '-', money), '-1,2|34');
  equal(typed('-1,2|34', '-', money), '1,2|34');
  equal(typed('12|34', '-', qty), '1,2|34');
});

Deno.test('a selection is replaced by what is typed', () => {
  const e = typeNatural({ text: '1,234,567', start: 2, end: 7 }, { insert: '9' }, qty);
  equal(shown(e), '1,9|67');
  const back = typeNatural({ text: '1,234,567', start: 0, end: 9 }, { back: true }, qty);
  equal(shown(back), '|');
});

Deno.test('a register takes digits from the cents, passes over a dot, Backspace drops one', () => {
  equal(typed('|', '1', till, typeRegister), '0.01|');
  equal(typed('|', '12', till, typeRegister), '0.12|');
  equal(typed('|', '123', till, typeRegister), '1.23|');
  equal(typed('|', '123456', till, typeRegister), '1,234.56|');
  equal(typed('|', '12.34', till, typeRegister), '12.34|');
  equal(typed('1,234.56|', '⌫', till, typeRegister), '123.45|');
  equal(typed('0.01|', '⌫', till, typeRegister), '|');
  // A zero typed is 0.00, not a blank; Backspace past the last digit is a blank.
  equal(typed('|', '00', till, typeRegister), '0.00|');
  equal(typed('|', '0', till, typeRegister), '0.00|');
  equal(typed('0.00|', '5', till, typeRegister), '0.05|');
  equal(typed('1.23|', '-', till, typeRegister), '-1.23|');
  equal(typed('-1.23|', '-', till, typeRegister), '1.23|');
  // All of it chosen: the next digit starts again.
  const e = typeRegister({ text: '1,234.56', start: 0, end: 8 }, { insert: '7' }, till);
  equal(shown(e), '0.07|');
});

Deno.test('leaving a field pads its fraction where it has fixed places', () => {
  equal(
    ['1,234.5', '1,234', '1,234.', '0.123', '-', ''].map((t) => padded(t, money)),
    ['1,234.50', '1,234.00', '1,234.00', '0.123', '-', ''],
  );
  equal(padded('1,234.5', qty), '1,234.5');
});

Deno.test('a value is shown grouped; a register at its places', () => {
  equal(['', '1234.5', '-42', '0'].map((v) => shownText(v, money)), [
    '',
    '1,234.5',
    '-42',
    '0',
  ]);
  equal(['', '1234.5', '-42', '0', '0.00'].map((v) => shownText(v, till)), [
    '',
    '1,234.50',
    '-42.00',
    '0.00',
    '0.00',
  ]);
});

Deno.test('a decimal shifts by places exactly', () => {
  equal(shift('0.12345678', 8), '12345678');
  equal(shift('12345678', -8), '0.12345678');
  equal(shift('1', -8), '0.00000001');
  equal(shift('-1.5', 2), '-150');
  equal(shift('0', 8), '0');
  equal(shift('123.45', 0), '123.45');
});

Deno.test('what a field holds: a decimal, a number, or the smallest unit', () => {
  // A decimal, as text.
  equal(valueOf('1234.50', {}), '1234.50');
  equal(textOf('1234.50', {}), '1234.50');
  // A JS number: refused past 15 significant digits.
  equal(valueOf('1234.5', { valueType: 'number' }), 1234.5);
  equal(valueOf('1234567890.12345', { valueType: 'number' }), 1234567890.12345);
  equal(valueOf('1234567890.123456', { valueType: 'number' }), undefined);
  equal(textOf(1e21, { valueType: 'number' }), '1000000000000000000000');
  // The smallest unit: cents, and sats.
  equal(String(valueOf('12.34', { valueType: 'minor', minorDigits: 2 })), '1234');
  equal(valueOf('12.345', { valueType: 'minor', minorDigits: 2 }), undefined);
  equal(textOf(1234n, { valueType: 'minor', minorDigits: 2 }), '12.34');
  // Bitcoin held as BTC, shown in sats; and held as sats, shown in BTC.
  equal(textOf('0.12345678', { show: 8 }), '12345678');
  equal(valueOf('12345678', { show: 8 }), '0.12345678');
  equal(textOf(12345678n, { valueType: 'minor', minorDigits: 8 }), '0.12345678');
  equal(String(valueOf('0.12345678', { valueType: 'minor', minorDigits: 8 })), '12345678');
  equal(textOf(12345678n, { valueType: 'minor', show: 0 }), '12345678');
  // A blank is null; text that isn't a number can't be held.
  equal(valueOf('', {}), null);
  equal(valueOf('12a', {}), undefined);
  equal(textOf(null, {}), '');
});
