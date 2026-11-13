/// <reference lib="deno.ns" />
// Dates and times as people type them (requirements S12.18.10, S12.18.11), and the month a
// calendar shows: every form read, every key's move, the bounds.
import {
  addDays,
  addMonths,
  dateText,
  daysIn,
  isoOf,
  monthGrid,
  moveDay,
  outside,
  readDate,
  readTime,
  timeText,
  within,
} from '../dates.js';
import { equal } from './assert.js';

const TODAY = '2026-11-13';

Deno.test('a date typed in each way people write one', () => {
  const read = (/** @type {string} */ t) => readDate(t, TODAY);
  equal(
    [
      '10/12/2026',
      '10/12/26',
      '10/12',
      '10-12-2026',
      '10.12.2026',
      '2026-10-12',
      'oct 12',
      'Oct 12, 2026',
      'october 12 2026',
      'Oct. 12',
      '12 oct 2026',
      '12 October',
      'sept 3',
      'today',
      '  TODAY ',
    ].map(read),
    [
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-10-12',
      '2026-09-03',
      TODAY,
      TODAY,
    ],
  );
});

Deno.test('what is not a date is not read as one', () => {
  const read = (/** @type {string} */ t) => readDate(t, TODAY);
  equal(
    [
      '',
      '  ',
      '10/45',
      '2/30/2026',
      '13/1',
      'octx 12',
      'xyz 12',
      '12 octx',
      '12 xyz',
      'oct',
      '2026-13-01',
      '1/2/3/4',
      'yesterday',
    ].map(read),
    Array(13).fill(null),
  );
  // February's last day, in a leap year and not.
  equal([read('2/29/2028'), read('2/29/2027')], ['2028-02-29', null]);
});

Deno.test('a date reads as people read it; anything else as it is', () => {
  equal(
    [
      dateText('2026-10-12'),
      dateText('2026-01-01'),
      dateText('10/45'),
      dateText(null),
      dateText(''),
    ],
    ['Oct 12, 2026', 'Jan 1, 2026', '10/45', '', ''],
  );
  equal([isoOf(10000, 1, 1), isoOf(2026, 0, 1), daysIn(2026, 2), daysIn(2028, 2)], [
    null,
    null,
    28,
    29,
  ]);
});

Deno.test('a time typed in each way people write one, on the 24-hour clock without am or pm', () => {
  equal(
    [
      '5:30 pm',
      '5:30p',
      '530p',
      '5p',
      '5 PM',
      '5:30 a.m.',
      '12:00 am',
      '12 pm',
      '17:30',
      '1730',
      '0',
      'noon',
      'midnight',
      '7',
    ].map(readTime),
    [
      '17:30',
      '17:30',
      '17:30',
      '17:00',
      '17:00',
      '05:30',
      '00:00',
      '12:00',
      '17:30',
      '17:30',
      '00:00',
      '12:00',
      '00:00',
      '07:00',
    ],
  );
  equal(['', '25:00', '5:60', '13pm', '0am', 'x', '5:3'].map(readTime), Array(7).fill(null));
  equal(
    [timeText('17:30'), timeText('00:05'), timeText('12:00'), timeText('5pm'), timeText(null)],
    [
      '5:30 PM',
      '12:05 AM',
      '12:00 PM',
      '5pm',
      '',
    ],
  );
});

Deno.test('a month is six weeks, its neighbours left blank', () => {
  const oct = monthGrid(2026, 10);
  equal(oct.length, 42);
  // October 2026 starts on a Thursday.
  equal(oct.slice(0, 5), [null, null, null, null, '2026-10-01']);
  equal(oct.filter(Boolean).length, 31);
  equal(oct[34], '2026-10-31');
  equal(oct.slice(35), Array(7).fill(null));
});

Deno.test("each key moves the calendar's day", () => {
  const at = '2026-10-31'; // a Saturday
  const moves = [
    'ArrowLeft',
    'ArrowRight',
    'ArrowUp',
    'ArrowDown',
    'PageUp',
    'PageDown',
    'Home',
    'End',
    'Enter',
  ].map((key) => moveDay(at, { key }));
  equal(moves, [
    '2026-10-30',
    '2026-11-01',
    '2026-10-24',
    '2026-11-07',
    '2026-09-30',
    '2026-11-30',
    '2026-10-25',
    '2026-10-31',
    undefined,
  ]);
  // With Shift, a year; the day kept, or the month's last.
  equal(
    [
      moveDay('2028-02-29', { key: 'PageUp', shiftKey: true }),
      moveDay('2026-01-31', { key: 'PageDown', shiftKey: true }),
    ],
    ['2027-02-28', '2027-01-31'],
  );
  equal([addDays('2026-12-31', 1), addMonths('2026-01-31', 1), addMonths('2026-03-31', -13)], [
    '2027-01-01',
    '2026-02-28',
    '2025-02-28',
  ]);
});

Deno.test('the bounds: outside which, and held within', () => {
  const min = '2026-10-05', max = '2026-10-25';
  equal(['2026-10-04', '2026-10-05', '2026-10-25', '2026-10-26'].map((d) => outside(d, min, max)), [
    'before',
    null,
    null,
    'after',
  ]);
  equal([
    outside('2026-01-01', null, null),
    within('2026-10-01', min, max),
    within('2026-11-01', min, max),
    within('2026-10-10', min, max),
    within('2026-10-10', null, null),
  ], [null, min, max, '2026-10-10', '2026-10-10']);
});
