// Exact decimals (requirements S12.12, S13.8.2). The API writes money, quantities, prices and
// ratios as JSON numbers with their own digits, `1234.50`; `parseJson` reads every number written
// with a decimal point as a Dec, never a float. A Dec is a whole number of units at a scale
// (1234.50 is 123450 at scale 2), held in a BigInt, so adding, subtracting and comparing are
// exact. It refuses to become a float by accident: `Number(d)`, `d + 1` and `d > 0` throw; charts
// ask for `d.toNumber()` by name. In a request body it is written back as an exact number.

const SHAPE = /^([+-])?(\d+)(?:\.(\d*))?(?:[eE]([+-]?\d+))?$/;

export class Dec {
  /** @type {bigint} */
  #units;
  /** @type {number} */
  #scale;

  /** @param {bigint} units @param {number} scale */
  constructor(units, scale) {
    this.#units = units;
    this.#scale = scale;
  }

  /** A Dec from a number's text: "1234.50", "-0.0345", "1e-05". @param {string} text */
  static parse(text) {
    const m = SHAPE.exec(String(text).trim());
    if (!m) throw new TypeError(`${text} is not a decimal number`);
    const [, sign, whole, frac = '', exp = '0'] = m;
    let units = BigInt(whole + frac);
    let scale = frac.length - Number(exp);
    if (scale < 0) {
      units *= 10n ** BigInt(-scale);
      scale = 0;
    }
    return new Dec(sign === '-' ? -units : units, scale);
  }

  /**
   * A Dec from what a form field or the API gives: a Dec, its text, or a whole number. A
   * fractional JS number is refused: it has already been through a float.
   * @param {Dec | string | number | bigint} x
   */
  static of(x) {
    if (x instanceof Dec) return x;
    if (typeof x === 'bigint') return new Dec(x, 0);
    if (typeof x === 'number') {
      if (!Number.isSafeInteger(x)) throw new TypeError(`${x} is not exact: pass its text`);
      return new Dec(BigInt(x), 0);
    }
    return Dec.parse(x);
  }

  /** The sum of a list, exact. @param {Iterable<Dec | string | number>} xs */
  static sum(xs) {
    let t = new Dec(0n, 0);
    for (const x of xs) t = t.add(Dec.of(x));
    return t;
  }

  get scale() {
    return this.#scale;
  }

  /** @param {number} scale */
  #at(scale) {
    return this.#units * 10n ** BigInt(scale - this.#scale);
  }

  /** @param {Dec | string | number} other */
  add(other) {
    const o = Dec.of(other), s = Math.max(this.#scale, o.#scale);
    return new Dec(this.#at(s) + o.#at(s), s);
  }

  /** @param {Dec | string | number} other */
  sub(other) {
    return this.add(Dec.of(other).neg());
  }

  /** @param {Dec | string | number} other */
  mul(other) {
    const o = Dec.of(other);
    return new Dec(this.#units * o.#units, this.#scale + o.#scale);
  }

  neg() {
    return new Dec(-this.#units, this.#scale);
  }

  abs() {
    return this.#units < 0n ? this.neg() : this;
  }

  /** -1, 0 or 1 against another. @param {Dec | string | number} other */
  cmp(other) {
    const o = Dec.of(other), s = Math.max(this.#scale, o.#scale);
    const a = this.#at(s), b = o.#at(s);
    return a < b ? -1 : a > b ? 1 : 0;
  }

  /** @param {Dec | string | number} other */
  eq(other) {
    return this.cmp(other) === 0;
  }

  /** @param {Dec | string | number} other */
  lt(other) {
    return this.cmp(other) < 0;
  }

  /** @param {Dec | string | number} other */
  gt(other) {
    return this.cmp(other) > 0;
  }

  /** -1, 0 or 1. */
  sign() {
    return this.#units < 0n ? -1 : this.#units > 0n ? 1 : 0;
  }

  isZero() {
    return this.#units === 0n;
  }

  isNegative() {
    return this.#units < 0n;
  }

  /** Rounded half to even to `places`, as the server rounds (S14.3). @param {number} places */
  round(places) {
    if (places >= this.#scale) return new Dec(this.#at(places), places);
    const f = 10n ** BigInt(this.#scale - places);
    let q = this.#units / f;
    const r = this.#units % f, half = f / 2n, ar = r < 0n ? -r : r;
    if (ar > half || (ar === half && q % 2n !== 0n)) q += this.#units < 0n ? -1n : 1n;
    return new Dec(q, places);
  }

  /**
   * This divided by another, rounded to `places`: a share of a total, say.
   * @param {Dec | string | number} other @param {number} places
   */
  div(other, places) {
    const o = Dec.of(other);
    if (o.isZero()) throw new RangeError('division by zero');
    // Two more places than asked for, so the rounding sees the next digits.
    const extra = places + 2;
    const n = this.#units * 10n ** BigInt(extra + o.#scale);
    const d = o.#units * 10n ** BigInt(this.#scale);
    return new Dec(n / d, extra).round(places);
  }

  /** The digits, with the scale it carries: "1234.50", "-0.0345". */
  toString() {
    const neg = this.#units < 0n;
    let digits = (neg ? -this.#units : this.#units).toString();
    if (this.#scale === 0) return (neg ? '-' : '') + digits;
    digits = digits.padStart(this.#scale + 1, '0');
    const cut = digits.length - this.#scale;
    return (neg ? '-' : '') + digits.slice(0, cut) + '.' + digits.slice(cut);
  }

  /** A float, for what only draws it (a chart's point, a bar's width). Never for sums. */
  toNumber() {
    return Number(this.toString());
  }

  /** Written into a request body as an exact number literal. */
  toJSON() {
    return /** @type {any} */ (JSON).rawJSON(this.toString());
  }

  valueOf() {
    throw new TypeError(
      `a Dec is exact and doesn't turn into a float: use its methods, or toNumber() to draw it`,
    );
  }

  /** @param {string} hint */
  [Symbol.toPrimitive](hint) {
    if (hint === 'string') return this.toString();
    return this.valueOf();
  }
}

/**
 * JSON as the API writes it: every number with a decimal point or an exponent as a Dec, a
 * whole number (a count, a year, sats) as a number. @param {string} text
 */
export function parseJson(text) {
  return JSON.parse(
    text,
    /** @type {any} */ (
      /** @param {string} _k @param {unknown} v @param {{ source?: string }} [ctx] */
      (_k, v, ctx) =>
        typeof v === 'number' && ctx?.source && /[.eE]/.test(ctx.source) ? Dec.parse(ctx.source) : v
    ),
  );
}

/** Whether a value is a Dec. @param {unknown} x @returns {x is Dec} */
export function isDec(x) {
  return x instanceof Dec;
}

/**
 * A float for what is only drawn or shown as a rough share (a bar's width, a chart's point, a
 * percentage): from a Dec, its text or a number; nothing counts as 0. Never for amounts.
 * @param {unknown} x
 */
export function num(x) {
  if (x == null || x === '') return 0;
  return x instanceof Dec ? x.toNumber() : Number(x);
}

/** An amount as a Dec, nothing as 0. @param {Dec | string | number | null | undefined} x */
export function dec(x) {
  return x == null || x === '' ? new Dec(0n, 0) : Dec.of(x);
}

/**
 * Data for a chart, which only draws: every Dec inside it, however deep, as a float.
 * @template T @param {T} x @returns {any}
 */
export function floats(x) {
  if (x instanceof Dec) return x.toNumber();
  if (Array.isArray(x)) return x.map(floats);
  if (x && typeof x === 'object') {
    return Object.fromEntries(Object.entries(x).map(([k, v]) => [k, floats(v)]));
  }
  return x;
}
