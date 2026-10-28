// The few assertions the browser modules' unit tests need (requirements S17.5), so `deno test`
// runs with nothing beyond the vendored libraries.

/** @param {unknown} a @param {unknown} b @param {string} [what] */
export function equal(a, b, what = '') {
  const x = JSON.stringify(a), y = JSON.stringify(b);
  if (x !== y) throw new Error(`${what ? what + ': ' : ''}${x} is not ${y}`);
}

/** @param {unknown} ok @param {string} [what] */
export function truthy(ok, what = 'expected true') {
  if (!ok) throw new Error(what);
}

/** @param {() => unknown} fn @param {string} [what] */
export function throws(fn, what = 'expected it to throw') {
  try {
    fn();
  } catch {
    return;
  }
  throw new Error(what);
}
