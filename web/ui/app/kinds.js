// The kinds of value a field takes (requirements S12.18, R3.11): for each, the characters it
// takes, how a paste is cleaned, and its whole-value check. Plain data and functions, so they
// are tested without a page; `<TypedInput>` (components/fields.js) draws them.
import { Dec } from './dec.js';
import { parseDuration } from './duration.js';

/**
 * How a field bounds its kind: whether it takes a negative, its least and most (`min` and
 * `max`, which its Min, Max or All fill in), and bounds with no button: a value it must be more
 * than (`above`: a loan's principal, more than 0) and its most (`atMost`: a rate's 40%).
 * @typedef {{ negative?: boolean, min?: number | string, max?: number | string,
 *   above?: number | string, atMost?: number | string }} Bounds
 */

/**
 * A kind: `chars` tests one character (null: any), `takes` names them, `read` checks a whole
 * value (a blank isn't checked here: a refused blank is refused at Save).
 * @typedef {{ chars: RegExp | null, takes: string[], inputmode?: string, numeric?: boolean,
 *   read: (text: string) => string | null }} Kind
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
  money: {
    chars: /[0-9.]/,
    takes: ['Digits', '.'],
    inputmode: 'decimal',
    numeric: true,
    read: decimal(2, 'Type an amount, such as 1234.50.'),
  },
  quantity: {
    chars: /[0-9.]/,
    takes: ['Digits', '.'],
    inputmode: 'decimal',
    numeric: true,
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
 */
export function check(k, b, text, format = String) {
  const t = text.trim();
  if (t === '') return null;
  const bad = k.read(t);
  if (bad) return bad;
  if (t.startsWith('-') && !b.negative) return `${format(0)} or more.`;
  if (!k.numeric) return null;
  const v = Dec.parse(t.replace('%', ''));
  if (b.above != null && !v.gt(bound(b.above))) return `More than ${format(b.above)}.`;
  if (b.min != null && v.lt(bound(b.min))) return `${format(b.min)} or more.`;
  const most = b.max ?? b.atMost;
  if (most != null && v.gt(bound(most))) return `${format(most)} or less.`;
  return null;
}
