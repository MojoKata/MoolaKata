// Numbers as they are typed (requirements S12.18.8): the digits sit at the field's right end and
// the commas that group them appear as they are typed. Pure functions over the field's text and
// its caret, so every case is a test without a page; `<TypedInput>` applies what they return.
//
// Two ways of typing: `natural`, as a number is written (a `.` starts the fraction), the caret
// keeping as many digits to its right after each change as it had before; and `register`, as a
// cash register takes an amount, each digit coming in at the right of the smallest unit.

/**
 * The field's text and its caret (or selection). `text` is what is shown, grouped; `refused`,
 * why a key wasn't taken, the text left as it was.
 * @typedef {{ text: string, start: number, end: number, refused?: string }} Edit
 */

/**
 * What a key or a paste does: put text in at the selection, or take out the character before
 * (`back`) or after (`forward`) the caret, or the selection.
 * @typedef {{ insert: string } | { back: true } | { forward: true }} Op
 */

/**
 * How a field takes a number: its places (null: as many as typed), whether it takes a negative,
 * and how it is typed.
 * @typedef {{ places: number | null, negative: boolean, entry: 'natural' | 'register' }} Way
 */

/** The text without its grouping commas. @param {string} t */
export const ungroup = (t) => t.replace(/,/g, '');

/**
 * A number's text grouped by thousands, as far as it is typed: `-1234.5` → `-1,234.5`; a
 * trailing `.`, a lone `-` and a blank stay as they are.
 * @param {string} t ungrouped
 */
export function groupText(t) {
  const m = /^(-?)(\d*)(\.?)(\d*)$/.exec(t);
  if (!m) return t;
  const [, sign, whole, dot, frac] = m;
  return sign + whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',') + dot + frac;
}

/** How many digits lie after position `at` of `text`. @param {string} text @param {number} at */
const digitsAfter = (text, at) => (text.slice(at).match(/\d/g) || []).length;

/**
 * The place in `text` with `n` digits after it: just after the digit before them, so the caret
 * stays against what was typed or kept, a comma or a `.` after it rather than before.
 * @param {string} text @param {number} n
 */
function placeBefore(text, n) {
  const total = (text.match(/\d/g) || []).length;
  const keep = total - n;
  if (keep <= 0) return text.search(/\d|\.|$/);
  let seen = 0;
  for (let i = 0; i < text.length; i++) {
    if (/\d/.test(text[i]) && ++seen === keep) return i + 1;
  }
  return text.length;
}

/**
 * A number typed as written: its integer part without leading zeros (a lone `0` before a `.`
 * kept), one `.` at most (none where the way has no places), and its sign kept in front.
 * @param {string} t ungrouped, as edited @param {Way} way
 */
function tidy(t, way) {
  let sign = t.startsWith('-') ? '-' : '';
  let body = t.replace(/-/g, '');
  const dot = body.indexOf('.');
  if (dot >= 0) body = body.slice(0, dot + 1) + body.slice(dot + 1).replace(/\./g, '');
  if (way.places === 0) body = body.replace(/\./g, '');
  let [whole, frac] = body.split('.');
  whole = whole.replace(/^0+(?=\d)/, '');
  if (frac !== undefined && whole === '') whole = '0';
  if (!way.negative) sign = '';
  return sign + whole + (frac !== undefined ? '.' + frac : '');
}

/**
 * One key or paste, typed as written (S12.18.8): the text it leaves and where the caret goes,
 * as many digits to its right as before. Backspace just after a comma takes the digit before
 * it. A `-` changes the sign wherever the caret is. Characters a number doesn't take are left
 * out; the caller refuses the key before it gets here.
 * @param {Edit} e @param {Op} op @param {Way} way @returns {Edit}
 */
export function typeNatural(e, op, way) {
  const flat = ungroup(e.text);
  // Positions in the ungrouped text.
  const at = (/** @type {number} */ i) => ungroup(e.text.slice(0, i)).length;
  let s = at(e.start), t = at(e.end);
  let out = flat;
  let after;
  if ('insert' in op) {
    // A field with no places (sats) takes no `.`: refused, as a digit past the places is.
    if (way.places === 0 && op.insert.includes('.')) {
      return { ...e, refused: 'Whole numbers only.' };
    }
    const minus = op.insert.includes('-');
    let put = op.insert.replace(/[^\d.]/g, '');
    // One `.` at most: a second is passed over. Typed before digits, those become the fraction.
    if ((flat.slice(0, s) + flat.slice(t)).includes('.')) put = put.replace(/\./g, '');
    out = flat.slice(0, s) + put + flat.slice(t);
    after = digitsAfter(flat, t);
    if (minus && way.negative) {
      out = out.startsWith('-') ? out.slice(1) : '-' + out;
    }
  } else {
    if (s === t) {
      if ('back' in op) s = Math.max(0, s - 1);
      else t = Math.min(flat.length, t + 1);
    }
    out = flat.slice(0, s) + flat.slice(t);
    after = digitsAfter(flat, t);
  }
  const tidied = tidy(out, way);
  // A digit past the field's places is not taken (S12.18.8.2): dollars stop at the cents.
  const frac = tidied.split('.')[1];
  if ('insert' in op && way.places != null && frac !== undefined && frac.length > way.places) {
    const was = ungroup(e.text).split('.')[1] ?? '';
    if (frac.length > was.length) return { ...e, refused: `At most ${way.places} places.` };
  }
  const text = groupText(tidied);
  let caret = placeBefore(text, after);
  // A `.` just typed: the caret goes on past it, to the fraction.
  if ('insert' in op && op.insert.endsWith('.') && text[caret] === '.') caret += 1;
  return { text, start: caret, end: caret };
}

/**
 * The digits of a register's amount: the value in its smallest unit, without leading zeros.
 * @param {string} t ungrouped, as shown @param {number} places
 */
function registerDigits(t, places) {
  const m = /^-?(\d*)(?:\.(\d*))?$/.exec(t);
  if (!m) return '';
  const frac = (m[2] || '').padEnd(places, '0').slice(0, places);
  return (m[1] + frac).replace(/^0+/, '');
}

/** A register's digits shown at their places: `123` → `1.23`. @param {string} digits @param {number} places */
function registerText(digits, places) {
  if (digits === '') return '';
  const d = digits.padStart(places + 1, '0');
  return places ? d.slice(0, -places) + '.' + d.slice(-places) : d;
}

/**
 * One key or paste, typed as a cash register takes it (S12.18.8.1): each digit comes in at the
 * right of the smallest unit, `.` is passed over, Backspace takes the last digit off, `-`
 * changes the sign. The caret stays at the end. A paste is read as a whole amount instead
 * (`readPaste`), so `1,234.5` is 1,234.50, not 12,345 cents.
 * @param {Edit} e @param {Op} op @param {Way} way @returns {Edit}
 */
export function typeRegister(e, op, way) {
  const places = way.places ?? 2;
  const flat = ungroup(e.text);
  const neg = flat.startsWith('-');
  const all = e.start === 0 && e.end === e.text.length && e.text !== '';
  let digits = all ? '' : registerDigits(flat, places);
  let sign = neg && !all;
  let zero = false;
  if ('insert' in op) {
    if (op.insert.includes('-') && way.negative) sign = !sign;
    const typed = op.insert.replace(/\D/g, '');
    digits = (digits + typed).replace(/^0+/, '');
    // A zero typed is an amount of nothing: 0.00, not a blank.
    zero = digits === '' && (typed !== '' || e.text !== '');
  } else if (!all) {
    digits = digits.slice(0, -1);
  }
  const body = registerText(zero ? '0' : digits, places);
  const text = groupText((sign && way.negative ? '-' : '') + body);
  return { text, start: text.length, end: text.length };
}

/**
 * Leaving a field typed as written: its fraction padded to its places, where it has a fixed
 * number (`1,234.5` → `1,234.50`); a lone `-` or `.` is left for the check to mark.
 * @param {string} text grouped @param {Way} way
 */
export function padded(text, way) {
  if (way.places == null || way.places === 0) return text;
  const m = /^(-?[\d,]+)(?:\.(\d*))?$/.exec(text);
  if (!m) return text;
  const frac = m[2] ?? '';
  if (frac.length > way.places) return text;
  return m[1] + '.' + frac.padEnd(way.places, '0');
}

/**
 * A value's text as a field shows it: grouped, a register's at its places.
 * @param {string} value ungrouped @param {Way} way
 */
export function shownText(value, way) {
  const t = String(value ?? '').trim();
  if (t === '') return '';
  if (way.entry === 'register' && /^-?\d*(\.\d*)?$/.test(t) && /\d/.test(t)) {
    const places = way.places ?? 2;
    const digits = registerDigits(t, places) || '0';
    const sign = t.startsWith('-') && digits !== '0' ? '-' : '';
    return groupText(sign + registerText(digits, places));
  }
  return groupText(t);
}

// ---------- what a number field holds (S17.3.10.2) ----------

/**
 * Shift a decimal's text by `n` places (`n` > 0: times 10^n), exactly, as text: `0.12345678`
 * shifted 8 is `12345678`.
 * @param {string} t @param {number} n
 */
export function shift(t, n) {
  if (!n || t === '' || t === '-') return t;
  const m = /^(-?)(\d*)(?:\.(\d*))?$/.exec(t);
  if (!m) return t;
  const [, sign, w, f = ''] = m;
  let digits = w + f;
  let point = w.length + n;
  if (point < 0) {
    digits = '0'.repeat(-point) + digits;
    point = 0;
  }
  if (point > digits.length) digits = digits.padEnd(point, '0');
  let whole = digits.slice(0, point).replace(/^0+(?=\d)/, '') || '0';
  const frac = digits.slice(point).replace(/0+$/, '');
  if (whole === '' && frac === '') whole = '0';
  const out = whole + (frac ? '.' + frac : '');
  return out === '0' ? '0' : sign + out;
}

/**
 * How a number field's value is held (S17.3.10.2): an exact decimal (`dec`, a `Dec` or its
 * text), a JS number in whole units (`number`), or an integer of the smallest unit (`minor`,
 * `minorDigits` places below a whole one: 2 for cents, 8 for sats). `show` is how many places
 * what is shown and typed sits from a whole unit of what is held: 8 shows bitcoin held as BTC
 * in sats; -8 shows sats held as an integer in BTC (with `minor`, where it is counted from the
 * smallest unit).
 * @typedef {{ valueType?: 'dec' | 'number' | 'minor', minorDigits?: number, show?: number }} Held
 */

/** Most significant digits a JS number holds exactly. */
export const NUMBER_DIGITS = 15;

/**
 * The text a field shows for what it holds.
 * @param {any} value @param {Held} held
 */
export function textOf(value, held) {
  if (value == null || value === '') return '';
  const type = held.valueType ?? 'dec';
  let t = String(value);
  if (type === 'number') t = numberText(/** @type {number} */ (value));
  if (type === 'minor') t = shift(String(BigInt(value)), -(held.minorDigits ?? 0));
  return shift(t, held.show ?? 0);
}

/** A JS number as plain decimal text, never in exponent form. @param {number} n */
function numberText(n) {
  if (!Number.isFinite(n)) return '';
  const s = String(n);
  if (!/e/i.test(s)) return s;
  if (Number.isInteger(n)) return BigInt(n).toString();
  return n.toFixed(20).replace(/\.?0+$/, '');
}

/**
 * What a field holds for the text typed, or `undefined` where the text can't be held as asked:
 * a `number` past 15 significant digits, a `minor` with more places than its smallest unit.
 * A blank is null.
 * @param {string} text ungrouped @param {Held} held
 * @returns {string | number | bigint | null | undefined}
 */
export function valueOf(text, held) {
  const t = text.trim();
  if (t === '') return null;
  if (!/^-?\d+(\.\d*)?$/.test(t)) return undefined;
  const base = shift(t, -(held.show ?? 0));
  const type = held.valueType ?? 'dec';
  if (type === 'number') {
    const sig = base.replace(/^-/, '').replace('.', '').replace(/^0+/, '');
    if (sig.length > NUMBER_DIGITS) return undefined;
    return Number(base);
  }
  if (type === 'minor') {
    const units = shift(base, held.minorDigits ?? 0);
    if (units.includes('.')) return undefined;
    return BigInt(units);
  }
  // An exact decimal with a smallest unit (bitcoin in BTC: 8) holds no more places than it.
  if (held.minorDigits != null && (base.split('.')[1] ?? '').length > held.minorDigits) {
    return undefined;
  }
  return base;
}
