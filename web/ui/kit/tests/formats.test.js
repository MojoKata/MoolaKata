/// <reference lib="deno.ns" />
// What depends on the person (S17.3.10.2): the format functions take the time zone or bitcoin
// unit as an argument, and `formatsFor` binds them, with the defaults for what is not given.
import { equal } from './assert.js';
import { bitcoin, day, moment, thisYear, today } from '../format.js';
import { formatsFor } from '../formats.js';

// 2026-01-01 03:30 UTC: still Dec 31 in Chicago, already Jan 1 in Tokyo.
const AT = '2026-01-01T03:30:00Z';

Deno.test('a moment and its day are in the zone given', () => {
  equal(moment(AT, 'UTC'), 'Jan 1, 2026, 3:30 AM');
  equal(moment(AT, 'America/Chicago'), 'Dec 31, 2025, 9:30 PM');
  equal(day(AT, 'America/Chicago'), 'Dec 31, 2025');
  equal(day(AT, 'Asia/Tokyo'), 'Jan 1, 2026');
  equal([moment(null, 'UTC'), day(undefined, 'UTC')], ['—', '—']);
});

Deno.test('today and this year are in the zone given', () => {
  // Kiritimati (UTC+14) and Pago Pago (UTC−11) are a day apart at any hour.
  const ahead = today('Pacific/Kiritimati');
  const behind = today('Pacific/Pago_Pago');
  equal(/^\d{4}-\d{2}-\d{2}$/.test(ahead), true);
  equal(Date.parse(ahead) - Date.parse(behind), 86400000);
  equal(thisYear('Pacific/Kiritimati'), Number(ahead.slice(0, 4)));
});

Deno.test('bitcoin in the unit given, from BTC or from sats, exact', () => {
  equal(bitcoin('0.12345678', 'btc'), '0.12345678 BTC');
  equal(bitcoin('0.12345678', 'sats'), '12,345,678 sats');
  equal(bitcoin('-1.5', 'btc'), '−1.50000000 BTC');
  equal(bitcoin(150000000, 'sats', true), '150,000,000 sats');
  equal(bitcoin('150000000', 'btc', true), '1.50000000 BTC');
  equal(bitcoin(null, 'sats'), '—');
});

Deno.test('formatsFor binds the zone and unit given, and defaults what is not', () => {
  const none = formatsFor();
  equal([none.timezone, none.bitcoinUnit], ['UTC', 'btc']);
  equal(none.moment(AT), 'Jan 1, 2026, 3:30 AM');
  equal(none.bitcoin('1'), '1.00000000 BTC');
  const chicago = formatsFor({ timezone: 'America/Chicago', bitcoinUnit: 'sats' });
  equal([chicago.timezone, chicago.bitcoinUnit], ['America/Chicago', 'sats']);
  equal(chicago.moment(AT), 'Dec 31, 2025, 9:30 PM');
  equal(chicago.day(AT), 'Dec 31, 2025');
  equal(chicago.today(), today('America/Chicago'));
  equal(chicago.thisYear(), thisYear('America/Chicago'));
  equal(chicago.bitcoin('0.00012345'), '12,345 sats');
  equal(chicago.bitcoin(12345, true), '12,345 sats');
  // Anything but sats reads as BTC; a blank zone is the default.
  const odd = formatsFor({ timezone: '', bitcoinUnit: /** @type {any} */ ('mbtc') });
  equal([odd.timezone, odd.bitcoinUnit], ['UTC', 'btc']);
});
