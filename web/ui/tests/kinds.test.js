/// <reference lib="deno.ns" />
// The kinds of value a field takes (requirements S12.18, R3.11): the characters each takes, a
// paste cleaned or refused whole, and the check made when the field is left and at Save.
import {
  accepts,
  check,
  cleanPaste,
  kindOf,
  KINDS,
  says,
  URL_MOST,
  webAddress,
} from '../app/kinds.js';
import { equal, truthy } from './assert.js';

const money = KINDS.money, count = KINDS.count, none = {}, neg = { negative: true };

Deno.test('each kind takes its own characters, and says which', () => {
  const at = (/** @type {string} */ kind, /** @type {string} */ t, b = none) =>
    accepts(kindOf(kind), b, t);
  equal(['12', '.', '1.5'].map((t) => at('money', t)), [true, true, true]);
  equal(['a', '$', ',', ' ', '-', '%', 'e'].map((t) => at('money', t)), [
    false,
    false,
    false,
    false,
    false,
    false,
    false,
  ]);
  equal(at('money', '-', neg), true, 'a minus where a negative is taken');
  equal(['5.875%', '5'].map((t) => at('percent', t)), [true, true]);
  equal(['1', '.', '-'].map((t) => at('count', t)), [true, false, false]);
  equal(['2w 3d', '4H', '90m'].map((t) => at('duration', t)), [true, true, true]);
  equal(['x', '1.5', '-'].map((t) => at('duration', t)), [false, false, false]);
  equal(['https://x.com/a?b=1', ' ', 'a b'].map((t) => at('url', t)), [true, false, false]);
  equal(['anything at all, $1 -2%'].map((t) => at('text', t)), [true]);
  equal(at('nonsense-kind', '¿?'), true, 'an unknown kind takes anything');
  equal(says(money, none), 'Digits and . only.');
  equal(says(money, neg), 'Digits, . and - only.');
  equal(says(count, none), 'Digits only.');
  equal(says(count, neg), 'Digits and - only.');
  equal(says(KINDS.percent, none), 'Digits, . and % only.');
  equal(says(KINDS.duration, none), 'Digits, w, d, h, m and spaces only.');
  equal(says(KINDS.url, none), 'No spaces.');
  equal(says(KINDS.text, none), '');
});

Deno.test('a paste is cleaned, then taken whole or refused whole', () => {
  equal(cleanPaste(money, none, ' $1,234.50 '), '1234.50');
  equal(cleanPaste(money, none, '1 234.50'), '1234.50', 'a non-breaking space');
  equal(cleanPaste(money, neg, '−12.00'), '-12.00', 'a typographic minus');
  equal(cleanPaste(money, neg, '(12.00)'), '-12.00', 'parentheses where negatives are taken');
  equal(cleanPaste(money, none, '(12.00)'), null, 'and refused where they are not');
  equal(cleanPaste(money, none, '-12.00'), null);
  equal(cleanPaste(money, none, '12 USD'), null, 'never taken in part');
  equal(cleanPaste(money, none, '1.234,56'), null, 'a decimal comma is not a thousands comma');
  equal(cleanPaste(count, none, '1,284'), '1284');
  equal(cleanPaste(money, none, '12,34'), null, 'commas only where they group thousands');
  equal(cleanPaste(KINDS.duration, none, ' 2w 3d '), '2w 3d', 'spaces kept inside a duration');
  equal(cleanPaste(KINDS.url, none, ' https://x.com/item \n'), 'https://x.com/item');
  equal(cleanPaste(KINDS.url, none, 'https://x.com/a b'), null);
  equal(cleanPaste(KINDS.text, none, '  as typed  '), 'as typed');
});

Deno.test('the whole value is checked: its form, then its bounds; a blank never', () => {
  const at = (/** @type {string} */ kind, /** @type {string} */ t, b = none) =>
    check(kindOf(kind), b, t);
  equal(['', '  '].map((t) => at('money', t, { min: 1 })), [null, null]);
  equal(['0', '12', '12.5', '12.50', '12.'].map((t) => at('money', t)), [
    null,
    null,
    null,
    null,
    null,
  ]);
  equal(at('money', '12.505'), 'At most 2 places.');
  equal(at('money', '1.2.3'), 'Type an amount, such as 1234.50.');
  equal(at('money', '.5'), 'Type an amount, such as 1234.50.');
  equal(at('money', '-5'), '0 or more.', 'a negative where none is taken');
  equal(at('money', '-5', neg), null);
  equal(at('quantity', '0.00001'), null, 'a quantity takes any places');
  equal(at('quantity', '1..2'), 'Type a number, such as 2.5.');
  equal(['5.875%', '5', '5.'].map((t) => at('percent', t)), [null, null, null]);
  equal(['%5', '5%%', '5.8.7'].map((t) => at('percent', t)), [
    'Type a percent, such as 5.875%.',
    'Type a percent, such as 5.875%.',
    'Type a percent, such as 5.875%.',
  ]);
  equal(at('percent', '41%', { max: 40 }), '40 or less.');
  equal(['1', '0042'].map((t) => at('count', t)), [null, null]);
  equal(at('count', '1.5'), 'Type a whole number.');
  equal(at('duration', '2w 3d'), null);
  truthy(at('duration', '3d 2w'), 'a duration read as S12.13 says');
  truthy(at('duration', 'd'));
  equal(at('text', 'anything'), null);
});

Deno.test('bounds are exact, and say themselves as the field shows them', () => {
  const fmt = (/** @type {any} */ n) => `$${Number(n).toFixed(2)}`;
  equal(check(money, { min: 10, max: 1250 }, '10', fmt), null);
  equal(check(money, { min: 10, max: 1250 }, '1250.00', fmt), null);
  equal(check(money, { min: 10, max: 1250 }, '9.99', fmt), '$10.00 or more.');
  equal(check(money, { min: 10, max: 1250 }, '1250.01', fmt), '$1250.00 or less.');
  equal(check(money, { min: '0.01' }, '0', fmt), '$0.01 or more.');
  equal(check(count, { min: 1, max: 2 }, '0'), '1 or more.');
  equal(check(count, { min: 1, max: 2 }, '3'), '2 or less.');
  equal(check(money, { min: -5, negative: true }, '-5.01'), '-5 or more.');
  // Bounds with no button: a value it must be more than, and a most.
  equal(check(money, { above: 0 }, '0', fmt), 'More than $0.00.');
  equal(check(money, { above: 0 }, '0.01', fmt), null);
  equal(check(KINDS.percent, { atMost: 40 }, '40%'), null);
  equal(check(KINDS.percent, { atMost: 40 }, '40.001%'), '40 or less.');
  equal(check(money, { max: 10, atMost: 5 }, '7'), null, 'a max, when given, is the most');
  equal(
    check(KINDS.quantity, { max: '0.3' }, '0.30000000000000001'),
    '0.3 or less.',
    'compared as exact decimals, never floats',
  );
});

Deno.test('a web address is http or https with a host, up to 2,000 characters', () => {
  const ok = 'https://example.com/item';
  equal([ok, 'http://shop.lan', 'HTTPS://X.COM'].map(webAddress), [null, null, null]);
  const refused = 'A web address starting with https:// or http://.';
  equal(
    ['example.com/item', 'javascript:alert(1)', 'ftp://x.com', 'https://', 'mailto:a@b.c'].map(
      webAddress,
    ),
    [refused, refused, refused, refused, refused],
  );
  const long = 'https://x.com/' + 'a'.repeat(URL_MOST - 14);
  equal(long.length, URL_MOST);
  equal(webAddress(long), null);
  equal(webAddress(long + 'a'), 'At most 2,000 characters.');
  equal(webAddress('https://[::1'), refused, 'one the URL parser refuses');
});
