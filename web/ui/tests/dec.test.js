/// <reference lib="deno.ns" />
// Exact decimals (requirements S12.12).
import { Dec, parseJson } from '../app/dec.js';
import { equal, throws, truthy } from './assert.js';

Deno.test('a decimal keeps its own digits and adds exactly', () => {
  equal(Dec.parse('0.10').add(Dec.parse('0.20')).toString(), '0.30');
  equal(Dec.parse('1234.5').sub('0.05').toString(), '1234.45');
  equal(Dec.parse('1e-05').toString(), '0.00001');
});

Deno.test('rounding is half to even, as the server rounds', () => {
  equal(Dec.parse('2.345').round(2).toString(), '2.34');
  equal(Dec.parse('2.355').round(2).toString(), '2.36');
  equal(Dec.parse('7').round(2).toString(), '7.00');
});

Deno.test('a decimal never becomes a float by accident', () => {
  const d = Dec.parse('1.5');
  throws(() => Number(d));
  throws(() => Dec.of(0.1));
  truthy(d.eq('1.50'));
});

Deno.test('JSON numbers with a point arrive as decimals, whole numbers as numbers', () => {
  const x = parseJson('{"amount": 10.0, "count": 3}');
  truthy(x.amount instanceof Dec);
  equal(x.amount.toString(), '10.0');
  equal(x.count, 3);
  equal(JSON.stringify({ amount: Dec.parse('1234.50') }), '{"amount":1234.50}');
});
