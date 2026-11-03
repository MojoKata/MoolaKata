// A field's bounds (R3.11), apart from any component so it is tested on its own.

/**
 * Whether what is typed is past the field's bounds: not a number, under `min`, over `max`, or
 * not whole for a count. A blank isn't: it is refused when saved, not marked as typed.
 * @param {string} v @param {number | undefined} min @param {number | undefined} max
 * @param {boolean} whole
 */
export function outside(v, min, max, whole) {
  if (v.trim() === '' || (min == null && max == null)) return false;
  const n = Number(v.replace(/,/g, ''));
  return Number.isNaN(n) || (min != null && n < min) || (max != null && n > max) ||
    (whole && !Number.isInteger(n));
}
