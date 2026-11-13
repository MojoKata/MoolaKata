// Numbers and dates for display (requirements S12.4, S14.3, S14.9). Money arrives as decimal
// strings and is formatted from its digits, never through a float. Calendar dates are shown as
// written; moments (UTC timestamps) in the viewer's time zone.

/**
 * Split a decimal string into sign, whole part and fraction.
 * @param {string} s
 */
function parts(s) {
  const neg = s.startsWith('-');
  const [whole, frac = ''] = (neg ? s.slice(1) : s).split('.');
  return { neg, whole: whole.replace(/^0+(?=\d)/, ''), frac };
}

/** @param {string} whole */
function group(whole) {
  return whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

/**
 * Dollars with two places: "$1,234.50", "−$12.00" (a true minus sign).
 * @param {import('./dec.js').Dec | string | null | undefined} s
 * @param {{ sign?: boolean, cents?: boolean }} [opts]
 */
export function money(s, opts = {}) {
  if (s == null) return '—';
  const { neg, whole, frac } = parts(String(s));
  const cents = (frac + '00').slice(0, 2);
  let out = '$' + group(whole) + (opts.cents === false ? '' : '.' + cents);
  if (opts.cents === false && Number(cents) >= 50) {
    out = '$' + group(String(BigInt(whole) + 1n));
  }
  const zero = /^0*$/.test(whole + cents);
  if (neg && !zero) return '−' + out;
  return opts.sign && !zero ? '+' + out : out;
}

/** @param {import('./dec.js').Dec | string | null | undefined} s */
export function isNegative(s) {
  return s != null && String(s).startsWith('-') && !/^-0*(\.0*)?$/.test(String(s));
}

/**
 * A quantity or price to its own scale, grouped: "1,234.5678".
 * @param {import('./dec.js').Dec | string | null | undefined} s
 */
export function quantity(s) {
  if (s == null) return '—';
  const { neg, whole, frac } = parts(String(s));
  // A whole quantity arrives as "10.0" (S13.8.2) and reads "10".
  const f = /^0*$/.test(frac) ? '' : frac;
  return (neg ? '−' : '') + group(whole) + (f ? '.' + f : '');
}

/** How bitcoin amounts are shown: BTC or sats, the user's choice in Profile (S1.6.4). */
let btcUnit = 'btc';
/** @param {string} u */
export function setBitcoinUnit(u) {
  btcUnit = u === 'sats' ? 'sats' : 'btc';
}

/**
 * A bitcoin amount, as the user chose: "0.12345678 BTC" or "12,345,678 sats". From BTC (a
 * quantity) or, with `fromSats`, whole sats; exact either way.
 * @param {import('./dec.js').Dec | string | number | null | undefined} s
 * @param {boolean} [fromSats]
 */
export function bitcoin(s, fromSats = false) {
  if (s == null) return '—';
  let sats;
  if (fromSats) sats = BigInt(String(s));
  else {
    const { neg, whole, frac } = parts(String(s));
    const n = BigInt(whole || '0') * 100000000n + BigInt((frac + '00000000').slice(0, 8));
    sats = neg ? -n : n;
  }
  const neg = sats < 0n;
  const a = neg ? -sats : sats;
  if (btcUnit === 'sats') return (neg ? '−' : '') + group(a.toString()) + ' sats';
  const w = (a / 100000000n).toString();
  const f = (a % 100000000n).toString().padStart(8, '0');
  return `${neg ? '−' : ''}${group(w)}.${f} BTC`;
}

/**
 * A price: dollars with at least two places, more when it has them: "$424.10", "$0.0345".
 * @param {import('./dec.js').Dec | string | null | undefined} s
 */
export function price(s) {
  if (s == null) return '—';
  const { neg, whole, frac } = parts(String(s));
  return (neg ? '−' : '') + '$' + group(whole) + '.' + frac.replace(/0+$/, '').padEnd(2, '0');
}

/**
 * A percentage string ("5.12") as "+5.12%".
 * @param {import('./dec.js').Dec | string | null | undefined} s
 */
export function pct(s) {
  if (s == null) return '—';
  const neg = String(s).startsWith('-');
  return (neg ? '−' : '+') + String(s).replace('-', '') + '%';
}

/**
 * Abbreviated, for chart axes only: "$1.2M" (S12.4). Charts may use floats: they only draw.
 * With the axis's tick step, enough decimals that no two ticks read the same.
 * @param {number} n
 * @param {number} [step]
 */
export function short(n, step) {
  const a = Math.abs(n);
  const unit = a >= 1e6 ? 1e6 : a >= 1e3 ? 1e3 : 1;
  const usual = unit === 1e6 ? 2 : unit === 1e3 ? (a >= 1e5 ? 0 : 1) : 0;
  const needed = step ? Math.ceil(-Math.log10(step / unit) - 1e-9) : 0;
  const s = (a / unit).toFixed(Math.min(2, Math.max(usual, needed))) +
    (unit === 1e6 ? 'M' : unit === 1e3 ? 'K' : '');
  return (n < 0 ? '−$' : '$') + s;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/**
 * A calendar date ("2026-10-12") as written, never shifted: "Oct 12, 2026".
 * @param {string | null | undefined} iso
 * @param {{ year?: boolean }} [opts]
 */
export function date(iso, opts = {}) {
  if (!iso) return '—';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  return `${MONTHS[m - 1]} ${d}` + (opts.year === false ? '' : `, ${y}`);
}

/** The time zone moments are shown in: the user's (Profile), set at sign-in. */
let zone = 'UTC';
/** @param {string} z */
export function setZone(z) {
  zone = z || 'UTC';
}

/**
 * A moment in the viewer's zone: "Oct 12, 2026, 2:05 PM".
 * @param {string | null | undefined} iso
 */
export function moment(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en-US', {
    timeZone: zone,
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso));
}

/**
 * The day of a moment, in the viewer's zone: "Oct 12, 2026" (S14.9.1). A calendar date is
 * `date`'s, never shifted.
 * @param {string | null | undefined} iso
 */
export function day(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en-US', { timeZone: zone, dateStyle: 'medium' })
    .format(new Date(iso));
}

/** Today in the viewer's zone, as a calendar date: "2026-10-12" (S14.9.5). */
export function today() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: zone }).format(new Date());
}

/** This year in the viewer's zone (S14.9.5). */
export function thisYear() {
  return Number(today().slice(0, 4));
}

/**
 * How long ago, for "last updated" and "synced": "41 min ago", "yesterday".
 * @param {string | null | undefined} iso
 */
export function ago(iso) {
  if (!iso) return 'never';
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 2 * 86400) return 'yesterday';
  return `${Math.round(s / 86400)} days ago`;
}

/**
 * The slug a field's label makes, which its help heading carries (S12.7.3).
 * @param {string} label
 */
export function slug(label) {
  return String(label).toLowerCase().replace(/\(.*?\)/g, '').replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}

/** @param {string | null | undefined} name */
export function initials(name) {
  return String(name || '?').split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0])
    .join('').toUpperCase();
}

/**
 * Typed money as integer cents (a BigInt), for sums in the browser without floats; null when it
 * isn't a number. "−1,234.5" → -123450n.
 * @param {string} s
 */
export function cents(s) {
  const t = String(s ?? '').replace(/[$,\s]/g, '').replace('−', '-');
  const m = t.match(/^(-?)(\d*)(?:\.(\d{0,2}))?$/);
  if (!m || (!m[2] && !m[3])) return null;
  return (m[1] ? -1n : 1n) * (BigInt(m[2] || '0') * 100n + BigInt((m[3] || '').padEnd(2, '0')));
}

/** @param {bigint} c */
export function fromCents(c) {
  const neg = c < 0n;
  const s = (neg ? -c : c).toString().padStart(3, '0');
  return (neg ? '-' : '') + s.slice(0, -2) + '.' + s.slice(-2);
}
