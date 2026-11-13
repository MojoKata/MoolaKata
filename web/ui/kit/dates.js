// Dates and times of day as people type them (requirements S12.18.10, S12.18.11), and the month
// a calendar shows. Pure: a calendar date is `YYYY-MM-DD` text, never a Date in a time zone, so
// nothing here shifts a day; a time of day is `HH:MM`, on the 24-hour clock.

export const MONTHS = [
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
];
const SHORT = MONTHS.map((m) => m.slice(0, 3).toLowerCase());

/** @param {number} n @param {number} w */
const pad = (n, w = 2) => String(n).padStart(w, '0');

/** Days in a month (1 to 12). @param {number} y @param {number} m */
export const daysIn = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();

/** A date's text from its parts, or null where the day doesn't exist. @param {number} y @param {number} m @param {number} d */
export function isoOf(y, m, d) {
  if (!(y >= 1 && y <= 9999 && m >= 1 && m <= 12 && d >= 1 && d <= daysIn(y, m))) return null;
  return `${pad(y, 4)}-${pad(m)}-${pad(d)}`;
}

/** A date's parts. @param {string} iso */
export const partsOf = (
  iso,
) => /** @type {[number, number, number]} */ (iso.split('-').map(Number));

/**
 * A date as it is typed, or null where it isn't one: `10/12/2026`, `10/12/26` (the 2000s),
 * `10/12` (this year), `oct 12`, `Oct 12, 2026`, `12 oct 2026`, `2026-10-12` or `today`.
 * Dashes and dots may stand for slashes.
 * @param {string} text @param {string} today `YYYY-MM-DD`
 */
export function readDate(text, today) {
  const t = text.trim().toLowerCase().replace(/\s+/g, ' ');
  if (!t) return null;
  if (t === 'today') return today;
  const [ty] = partsOf(today);
  const year = (/** @type {string | undefined} */ y) =>
    y === undefined ? ty : y.length <= 2 ? 2000 + Number(y) : Number(y);
  let m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(t);
  if (m) return isoOf(Number(m[1]), Number(m[2]), Number(m[3]));
  m = /^(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?$/.exec(t);
  if (m) return isoOf(year(m[3]), Number(m[1]), Number(m[2]));
  // A month's name, then the day: "oct 12", "october 12, 2026".
  m = /^([a-z]+)\.? (\d{1,2})(?:,? (\d{2}|\d{4}))?$/.exec(t);
  if (m) {
    const mo = SHORT.indexOf(m[1].slice(0, 3));
    if (mo < 0 || !MONTHS[mo].toLowerCase().startsWith(m[1])) return null;
    return isoOf(year(m[3]), mo + 1, Number(m[2]));
  }
  // The day, then the month's name: "12 oct 2026".
  m = /^(\d{1,2}) ([a-z]+)\.?(?:,? (\d{2}|\d{4}))?$/.exec(t);
  if (m) {
    const mo = SHORT.indexOf(m[2].slice(0, 3));
    if (mo < 0 || !MONTHS[mo].toLowerCase().startsWith(m[2])) return null;
    return isoOf(year(m[3]), mo + 1, Number(m[1]));
  }
  return null;
}

/** A date as it reads: `Oct 12, 2026`; anything else as it is. @param {string | null | undefined} iso */
export function dateText(iso) {
  if (!iso) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!m) return iso;
  return `${MONTHS[Number(m[2]) - 1].slice(0, 3)} ${Number(m[3])}, ${Number(m[1])}`;
}

/**
 * A time of day as it is typed, as `HH:MM`, or null: `5:30 pm`, `5:30p`, `530p`, `5p`,
 * `17:30`, `1730`, `noon`, `midnight`. Without am or pm it is read on the 24-hour clock.
 * @param {string} text
 */
export function readTime(text) {
  const t = text.trim().toLowerCase().replace(/\s+/g, '');
  if (!t) return null;
  if (t === 'noon') return '12:00';
  if (t === 'midnight') return '00:00';
  const m = /^(\d{1,2})(?::?(\d{2}))?(a|p|am|pm|a\.m\.|p\.m\.)?$/.exec(t);
  if (!m) return null;
  let h = Number(m[1]);
  const min = m[2] === undefined ? 0 : Number(m[2]);
  if (min > 59) return null;
  const half = m[3]?.[0];
  if (half) {
    if (h < 1 || h > 12) return null;
    h = (h % 12) + (half === 'p' ? 12 : 0);
  } else if (h > 23) return null;
  return `${pad(h)}:${pad(min)}`;
}

/** A time of day as it reads: `17:30` → `5:30 PM`. @param {string | null | undefined} hm */
export function timeText(hm) {
  if (!hm) return '';
  const m = /^(\d{2}):(\d{2})$/.exec(hm);
  if (!m) return hm;
  const h = Number(m[1]);
  return `${h % 12 || 12}:${m[2]} ${h < 12 ? 'AM' : 'PM'}`;
}

// ---------- the calendar (S12.18.10.1) ----------

/**
 * A month as the calendar draws it: six weeks of seven days from the Sunday on or before its
 * first, each cell its date or null outside the month (a day of the month next door is left
 * blank, so it isn't read as this month's).
 * @param {number} y @param {number} m @returns {(string | null)[]}
 */
export function monthGrid(y, m) {
  const first = new Date(Date.UTC(y, m - 1, 1)).getUTCDay();
  const n = daysIn(y, m);
  return Array.from({ length: 42 }, (_, i) => {
    const d = i - first + 1;
    return d >= 1 && d <= n ? isoOf(y, m, d) : null;
  });
}

/** A date `n` days on (or back). @param {string} iso @param {number} n */
export function addDays(iso, n) {
  const [y, m, d] = partsOf(iso);
  const t = new Date(Date.UTC(y, m - 1, d + n));
  return /** @type {string} */ (isoOf(t.getUTCFullYear(), t.getUTCMonth() + 1, t.getUTCDate()));
}

/** A date `n` months on (or back), its day kept or the month's last. @param {string} iso @param {number} n */
export function addMonths(iso, n) {
  const [y, m, d] = partsOf(iso);
  const k = y * 12 + (m - 1) + n;
  const ny = Math.floor(k / 12), nm = (k % 12) + 1;
  return /** @type {string} */ (isoOf(ny, nm, Math.min(d, daysIn(ny, nm))));
}

/**
 * Where a key moves the calendar's day: ← → a day, ↑ ↓ a week, Page Up and Page Down a month
 * (Shift: a year), Home and End the week's first and last day. Undefined for a key the grid
 * doesn't move on.
 * @param {string} iso @param {{ key: string, shiftKey?: boolean }} e
 */
export function moveDay(iso, e) {
  const [y, m, d] = partsOf(iso);
  const weekday = new Date(Date.UTC(y, m - 1, d)).getUTCDay();
  switch (e.key) {
    case 'ArrowLeft':
      return addDays(iso, -1);
    case 'ArrowRight':
      return addDays(iso, 1);
    case 'ArrowUp':
      return addDays(iso, -7);
    case 'ArrowDown':
      return addDays(iso, 7);
    case 'PageUp':
      return addMonths(iso, e.shiftKey ? -12 : -1);
    case 'PageDown':
      return addMonths(iso, e.shiftKey ? 12 : 1);
    case 'Home':
      return addDays(iso, -weekday);
    case 'End':
      return addDays(iso, 6 - weekday);
  }
  return undefined;
}

/**
 * Whether a date is outside the bounds, and which: `before` `min`, `after` `max`, or null.
 * @param {string} iso @param {string | null | undefined} min @param {string | null | undefined} max
 */
export function outside(iso, min, max) {
  if (min && iso < min) return 'before';
  if (max && iso > max) return 'after';
  return null;
}

/** A date held within the bounds. @param {string} iso @param {string | null | undefined} min @param {string | null | undefined} max */
export const within = (iso, min, max) => min && iso < min ? min : max && iso > max ? max : iso;
