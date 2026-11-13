// The kinds of value a field takes (requirements S12.18, R3.11): for each, the characters it
// takes, how a paste is cleaned, and its whole-value check. Plain data and functions, so they
// are tested without a page; `<TypedInput>` (components/fields.js) draws them.
import { Dec } from './dec.js';
import { parseDuration } from './duration.js';
import { date, money, quantity, today } from './format.js';
import { readDate, readTime, timeText } from './dates.js';

/**
 * How a field bounds its kind: whether it takes a negative, its least and most (`min` and
 * `max`, which its Min, Max or All fill in), and bounds with no button: a value it must be more
 * than (`above`: a loan's principal, more than 0) and its most (`atMost`: a rate's 40%).
 * @typedef {{ negative?: boolean, min?: number | string, max?: number | string,
 *   above?: number | string, atMost?: number | string }} Bounds
 */

/**
 * A kind: `chars` tests one character (null: any), `takes` names them, `read` checks a whole
 * value (a blank isn't checked here: a refused blank is refused at Save). A number that groups
 * as it is typed (S12.18.8) says how it is typed (`entry`), its places (null: as typed) and the
 * unit before it (`prefix`); a date is read as people write it (S12.18.10).
 * @typedef {{ chars: RegExp | null, takes: string[], inputmode?: string, numeric?: boolean,
 *   entry?: 'natural' | 'register', places?: number | null, prefix?: string, date?: boolean,
 *   read: (text: string, today?: string) => string | null }} Kind
 */

/** @param {number | null} places @param {string} error @returns {(t: string) => string | null} */
const decimal = (places, error) => (t) => {
  const m = /^-?\d+(?:\.(\d*))?$/.exec(t);
  if (!m) return error;
  const frac = m[1] ?? '';
  return places !== null && frac.length > places ? `At most ${places} places.` : null;
};

/** @type {{ [kind: string]: Kind }} */
export const KINDS = {
  // Dollars, typed from the cents as a cash register takes them, `$` before them (S12.18.8.1).
  money: {
    chars: /[0-9.]/,
    takes: ['Digits', '.'],
    inputmode: 'decimal',
    numeric: true,
    entry: 'register',
    places: 2,
    prefix: '$',
    read: decimal(2, 'Type an amount, such as 1234.50.'),
  },
  // Shares, bitcoin and the like, typed as written (S12.18.8.2).
  quantity: {
    chars: /[0-9.]/,
    takes: ['Digits', '.'],
    inputmode: 'decimal',
    numeric: true,
    entry: 'natural',
    places: null,
    read: decimal(null, 'Type a number, such as 2.5.'),
  },
  percent: {
    chars: /[0-9.%]/,
    takes: ['Digits', '.', '%'],
    inputmode: 'decimal',
    numeric: true,
    read: (t) => (/^\d+(?:\.\d*)?%?$/.test(t) ? null : 'Type a percent, such as 5.875%.'),
  },
  count: {
    chars: /[0-9]/,
    takes: ['Digits'],
    inputmode: 'numeric',
    numeric: true,
    read: (t) => (/^-?\d+$/.test(t) ? null : 'Type a whole number.'),
  },
  duration: {
    chars: /[0-9dwhm ]/i,
    takes: ['Digits', 'w', 'd', 'h', 'm', 'spaces'],
    read: (t) => {
      const d = parseDuration(t);
      return 'error' in d ? d.error : null;
    },
  },
  date: {
    chars: null,
    takes: [],
    date: true,
    read: (t, now) => (readDate(t, now ?? today()) ? null : 'Type a date, such as 10/12/2026.'),
  },
  time: {
    chars: null,
    takes: [],
    read: (t) => (readTime(t) ? null : 'Type a time, such as 5:30 PM.'),
  },
  url: {
    chars: /\S/,
    takes: [],
    inputmode: 'url',
    read: (t) => webAddress(t),
  },
  text: { chars: null, takes: [], read: () => null },
};

/** Up to 2,000 characters, `http://` or `https://`, then a host (S7.8.1). */
export const URL_MOST = 2000;

/** Why a web address is refused, or null. @param {string} t */
export function webAddress(t) {
  const error = 'A web address starting with https:// or http://.';
  if (t.length > URL_MOST) return `At most ${URL_MOST.toLocaleString('en-US')} characters.`;
  if (!/^https?:\/\/\S/i.test(t)) return error;
  try {
    return new URL(t).hostname ? null : error;
  } catch {
    return error;
  }
}

/** A kind by name; an unknown one takes anything. @param {string} name */
export const kindOf = (name) => KINDS[name] || KINDS.text;

/** Whether one character is taken. @param {Kind} k @param {Bounds} b @param {string} c */
const takes = (k, b, c) =>
  !k.chars || k.chars.test(c) || (c === '-' && !!b.negative && !!k.numeric);

/** What a field takes, as its mark says it: "Digits, . and - only." @param {Kind} k @param {Bounds} b */
export function says(k, b) {
  if (!k.chars) return '';
  if (!k.takes.length) return 'No spaces.';
  const w = [...k.takes, ...(b.negative && k.numeric ? ['-'] : [])];
  return (w.length > 1 ? `${w.slice(0, -1).join(', ')} and ${w[w.length - 1]}` : w[0]) + ' only.';
}

/**
 * Whether typed text is taken whole: every character is the kind's.
 * @param {Kind} k @param {Bounds} b @param {string} text
 */
export function accepts(k, b, text) {
  return [...text].every((c) => takes(k, b, c));
}

/**
 * A paste, cleaned: for a number, a dollar sign, spaces and non-breaking spaces dropped,
 * commas dropped where they group thousands, a typographic minus made "-", and parentheses
 * made a minus where a negative is taken; any other text only trimmed. Null when anything
 * left isn't the kind's: the paste is refused whole, never taken in part.
 * @param {Kind} k @param {Bounds} b @param {string} text
 */
export function cleanPaste(k, b, text) {
  let s = text.trim();
  if (k.numeric) {
    s = s.replace(/[$\s ]/g, '').replace(/−/g, '-');
    const paren = /^\((.*)\)$/.exec(s);
    if (paren && b.negative) s = '-' + paren[1];
    // "1.234,56" uses a decimal comma: refused, never misread as 1.23456.
    if (s.includes(',')) {
      if (!/^-?\d{1,3}(?:,\d{3})+(?:\.\d*)?%?$/.test(s)) return null;
      s = s.replace(/,/g, '');
    }
  }
  return accepts(k, b, s) ? s : null;
}

/** @param {number | string} n */
const bound = (n) => Dec.parse(String(n));

/**
 * Why a value is marked, or null: its form, then its bounds. A blank is never marked: one that
 * is refused is refused at Save. `format` shows a bound as the field shows it.
 * @param {Kind} k @param {Bounds} b @param {string} text
 * @param {(n: number | string) => string} [format]
 * @param {string} [now]  today where the field is (a date's `today`, `tomorrow`)
 */
export function check(k, b, text, format = String, now = undefined) {
  const t = text.trim();
  if (t === '') return null;
  const bad = k.read(t, now);
  if (bad) return bad;
  if (k.date) {
    const iso = /** @type {string} */ (readDate(t, now ?? today()));
    if (b.min != null && iso < String(b.min)) return `On or after ${date(String(b.min))}.`;
    if (b.max != null && iso > String(b.max)) return `On or before ${date(String(b.max))}.`;
    return null;
  }
  if (t.startsWith('-') && !b.negative) return `${format(0)} or more.`;
  if (!k.numeric) return null;
  const v = Dec.parse(t.replace('%', ''));
  if (b.above != null && !v.gt(bound(b.above))) return `More than ${format(b.above)}.`;
  if (b.min != null && v.lt(bound(b.min))) return `${format(b.min)} or more.`;
  const most = b.max ?? b.atMost;
  if (most != null && v.gt(bound(most))) return `${format(most)} or less.`;
  return null;
}

// ---------- the read persona (S12.18.6) ----------

/**
 * A value as its kind reads it: an amount "$1,234.50", a quantity or a count grouped, a percent
 * with its "%", a date "Oct 12, 2026", anything else as it is; a blank "—". `format`, given,
 * reads a number as its field shows it (sats, a price).
 * @param {string} kind @param {any} value @param {(n: any) => string} [format]
 */
export function readText(kind, value, format) {
  const t = String(value ?? '').trim();
  if (t === '') return '—';
  const k = kindOf(kind);
  if (k.numeric && k.read(t)) return t;
  if (format && k.numeric) return format(t.replace(/%$/, ''));
  if (kind === 'money') return money(t);
  if (kind === 'quantity' || kind === 'count') return quantity(t);
  if (kind === 'percent') return quantity(t.replace(/%$/, '')) + '%';
  if (kind === 'date' && /^\d{4}-\d{2}-\d{2}$/.test(t)) return date(t);
  if (kind === 'time' && /^\d{2}:\d{2}$/.test(t)) return timeText(t);
  return t;
}
