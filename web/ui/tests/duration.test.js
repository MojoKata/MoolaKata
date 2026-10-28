/// <reference lib="deno.ns" />
// Durations as people type them (requirements S12.13).
import { formatDuration, parseDuration } from '../app/duration.js';
import { equal, truthy } from './assert.js';

Deno.test('one grammar, largest unit first, each at most once', () => {
  equal(parseDuration('2w 3d 4h'), { minutes: 2 * 10080 + 3 * 1440 + 240 });
  equal(parseDuration('2w3d'), { minutes: 2 * 10080 + 3 * 1440 });
  equal(parseDuration('90m'), { minutes: 90 });
  truthy('error' in parseDuration('3d 2w'), 'smaller unit first is refused');
  truthy('error' in parseDuration('1d 1d'), 'a unit twice is refused');
  truthy('error' in parseDuration(''), 'nothing is refused');
});

Deno.test('a duration is shown back as typed', () => {
  equal(formatDuration(2 * 10080 + 3 * 1440 + 240), '2w 3d 4h');
});
