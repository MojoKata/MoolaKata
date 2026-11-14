/// <reference lib="deno.ns" />
// Bitcoin typed in sats into a field that holds BTC (S1.6.4): the record keeps the text as
// typed and reads the BTC it is; text that isn't whole sats is refused, never read as BTC.
import { countedIds, Draft, Record } from '../app/draft.js';
import { inputSats } from '../app/sats.js';
import { Dec } from '../kit/dec.js';
import { equal } from '../kit/tests/assert.js';

class Lot extends Record {
  /** @override */
  static prefix = 'Lot';
  /** @override */
  static fields = { quantity: { type: 'quantity', nullable: true } };
  /** @override */
  static defaults = { quantity: null };
}

const SATS = { minorDigits: 8, show: 8 };

/** A lot with `text` typed into its quantity in sats. @param {string} text */
function typed(text) {
  const d = new Draft({ newId: countedIds(() => 0), post: () => Promise.resolve({ saved: [] }) });
  const rec = d.add(Lot, {});
  inputSats(rec, 'quantity', text, SATS);
  const q = rec.get('quantity');
  return {
    held: q == null ? q : Dec.of(q).toString(),
    shown: rec.shown('quantity'),
    why: rec.unreadWhy('quantity'),
  };
}

Deno.test('whole sats, grouped or not, are held as the BTC they are', () => {
  equal(typed('60000000'), { held: '0.6', shown: '60000000', why: null });
  equal(typed('12,345,678'), { held: '0.12345678', shown: '12,345,678', why: null });
  equal(typed('1'), { held: '0.00000001', shown: '1', why: null });
  equal(typed('250000000'), { held: '2.5', shown: '250000000', why: null });
});

Deno.test('a blank is no quantity', () => {
  equal(typed('').held, null);
  equal(typed('   ').held, null);
});

Deno.test('a fraction of a sat or a letter is refused, never read as BTC', () => {
  for (const text of ['1.5', '0.1', '12a', '-', 'abc']) {
    const t = typed(text);
    equal([t.held, t.shown, t.why], [null, text, 'Type whole sats, such as 12,345,678.'], text);
  }
});
