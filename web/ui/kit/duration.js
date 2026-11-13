// Durations as people type them (requirements S12.13): one or more parts, each a whole number
// and a unit, w (weeks), d (days), h (hours) or m (minutes), largest first, each unit at most
// once, with or without spaces: "1d", "90m", "2w 3d 4h", "2w3d". The server reads them with the
// same rules (moolakata/duration.py).

const MINUTES = /** @type {Record<string, number>} */ ({ w: 10080, d: 1440, h: 60, m: 1 });
const ORDER = 'wdhm';

/**
 * A duration's length in minutes, or an error worded for the field.
 * @param {string} text
 * @returns {{ minutes: number } | { error: string }}
 */
export function parseDuration(text) {
  const s = String(text ?? '').trim();
  if (!s) return { error: 'Type a duration, such as 1d or 2w 3d 4h.' };
  const part = /\s*(\d+)\s*([a-zA-Z]+)\s*/y;
  let total = 0, last = -1, pos = 0;
  while (pos < s.length) {
    part.lastIndex = pos;
    const m = part.exec(s);
    if (!m) return { error: `“${s.slice(pos).trim()}” isn't a number and a unit (w, d, h or m).` };
    const unit = m[2].toLowerCase();
    const at = ORDER.indexOf(unit);
    if (at < 0 || m[2].length !== 1) return { error: `“${m[2]}” isn't a unit: use w, d, h or m.` };
    if (at === last) return { error: `“${unit}” is given twice.` };
    if (at < last) return { error: 'Give the units largest first: w, then d, then h, then m.' };
    last = at;
    total += Number(m[1]) * MINUTES[unit];
    pos = part.lastIndex;
  }
  if (total <= 0) return { error: 'A duration is at least a minute.' };
  return { minutes: total };
}

/**
 * Minutes as a duration would be typed, largest units first: "2w 3d 4h".
 * @param {number} minutes
 */
export function formatDuration(minutes) {
  let left = Math.floor(minutes);
  const parts = [];
  for (const unit of ORDER) {
    const size = MINUTES[unit];
    if (left >= size) {
      parts.push(`${Math.floor(left / size)}${unit}`);
      left %= size;
    }
  }
  return parts.join(' ') || '0m';
}
