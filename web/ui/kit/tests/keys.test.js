/// <reference lib="deno.ns" />
// Home and End in typed text (requirements S12.18.13): which keys move, how far, and the
// selection left where the browser can't move by drawn lines.
import { homeEnd, moved } from '../keys.js';
import { equal } from './assert.js';

const line = { by: 'lineboundary' };
const all = { by: 'documentboundary' };

Deno.test('Home and End, with Shift, Ctrl or Cmd; Alt and other keys are not theirs', () => {
  equal(
    [
      homeEnd({ key: 'Home' }, false),
      homeEnd({ key: 'End', shiftKey: true }, false),
      homeEnd({ key: 'Home', ctrlKey: true }, true),
      homeEnd({ key: 'End', metaKey: true, shiftKey: true }, true),
      // One line: Ctrl or Cmd is still the line, which is all of it.
      homeEnd({ key: 'Home', metaKey: true }, false),
      homeEnd({ key: 'Home', altKey: true }, true),
      homeEnd({ key: 'ArrowLeft' }, true),
    ],
    [
      { dir: 'backward', ...line, extend: false },
      { dir: 'forward', ...line, extend: true },
      { dir: 'backward', ...all, extend: false },
      { dir: 'forward', ...all, extend: true },
      { dir: 'backward', ...line, extend: false },
      null,
      null,
    ],
  );
});

Deno.test('without drawn lines: the line runs between line breaks', () => {
  const text = 'one two\nthree four\nfive';
  const m = (/** @type {any} */ e) => /** @type {any} */ (homeEnd(e, true));
  const at = (/** @type {number} */ i, /** @type {any} */ e) => moved(text, i, i, 'none', m(e));
  equal(
    [
      at(10, { key: 'Home' }), // in the middle line
      at(10, { key: 'End' }),
      at(3, { key: 'Home' }), // the first line
      at(20, { key: 'End' }), // the last, no break after it
      at(8, { key: 'Home' }), // already at a line's start
      at(7, { key: 'End' }), // already at a line's end
      at(10, { key: 'Home', ctrlKey: true }),
      at(10, { key: 'End', metaKey: true }),
    ],
    [
      [8, 8, 'forward'],
      [18, 18, 'forward'],
      [0, 0, 'forward'],
      [23, 23, 'forward'],
      [8, 8, 'forward'],
      [7, 7, 'forward'],
      [0, 0, 'forward'],
      [23, 23, 'forward'],
    ],
  );
});

Deno.test('with Shift the selection grows from where it was anchored, either way', () => {
  const text = 'one two\nthree four\nfive';
  const m = (/** @type {any} */ e) => /** @type {any} */ (homeEnd({ ...e, shiftKey: true }, true));
  equal(
    [
      moved(text, 10, 10, 'none', m({ key: 'Home' })),
      moved(text, 10, 10, 'none', m({ key: 'End' })),
      // Selected forward from 9 to 12: End moves its focus, 12, to the line's end.
      moved(text, 9, 12, 'forward', m({ key: 'End' })),
      // Selected forward from 9 to 12: Home takes the focus past the anchor, so it turns back.
      moved(text, 9, 12, 'forward', m({ key: 'Home' })),
      // Selected backward (anchor 12): End takes the focus past it, forward.
      moved(text, 9, 12, 'backward', m({ key: 'End' })),
      moved(text, 9, 12, 'backward', m({ key: 'Home', ctrlKey: true })),
    ],
    [
      [8, 10, 'backward'],
      [10, 18, 'forward'],
      [9, 18, 'forward'],
      [8, 9, 'backward'],
      [12, 18, 'forward'],
      [0, 12, 'backward'],
    ],
  );
});
