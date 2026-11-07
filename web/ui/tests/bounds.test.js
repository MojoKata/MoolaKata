/// <reference lib="deno.ns" />
// A field's bounds (R3.11): what is typed is marked as soon as it is past them.
import { outside } from '../app/bounds.js';
import { equal } from './assert.js';

Deno.test('a count is from 1 to its max, whole', () => {
  const at = (/** @type {string} */ v) => outside(v, 1, 2, true);
  equal(['', ' ', '1', '2'].map(at), [false, false, false, false]);
  equal(['0', '3', '-1', '1.5', 'two', '2x'].map(at), [true, true, true, true, true, true]);
});

Deno.test('an amount is between its min and max, cents and commas allowed', () => {
  const at = (/** @type {string} */ v) => outside(v, 10, 1250, false);
  equal(['10', '1,250', '99.95'].map(at), [false, false, false]);
  equal(['9.99', '1,250.01', '$5'].map(at), [true, true, true]);
  equal(outside('7', undefined, 5, false), true);
  equal(outside('-3', 0, undefined, false), true);
});

Deno.test('a field with no bounds marks nothing', () => {
  equal(outside('anything', undefined, undefined, true), false);
});
