// Bitcoin typed in sats (S1.6.4), into a record's field that holds BTC.
import { ungroup, valueOf } from '../kit/numbers.js';

/**
 * Sats typed into a field that holds BTC: the record keeps the text as typed, and reads the BTC
 * it is. Text that isn't whole sats (a fraction of a sat, a letter) is never read as BTC: it is
 * refused at Save, as text that doesn't read is.
 * @param {import('../app/draft.js').Record} rec @param {string} name @param {string} v
 * @param {import('../kit/numbers.js').Held} held
 */
export function inputSats(rec, name, v, held) {
  const btc = valueOf(ungroup(v), held);
  if (btc === undefined) {
    rec.inputAs(name, v, () => ({ error: 'Type whole sats, such as 12,345,678.' }));
  } else rec.input(name, v, String(btc ?? ''));
}
