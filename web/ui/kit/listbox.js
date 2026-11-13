// Parts adapted from preact-components (MIT): see kit/NOTICE.md.
//
// A list of options under a box being typed in (requirements S12.18.12): which option the arrows
// reach, what Enter and Escape do, and which options match what is typed. Pure: the key table
// is decided without a page, so every key is a test; the component applies what it returns.

/**
 * The list's state: whether it is open, and the option the arrows reached (-1: none).
 * @typedef {{ open: boolean, active: number }} ListState
 */

/**
 * The keys the list answers, as `listKey` names them: `Alt` matters only on the arrows.
 * @typedef {'ArrowDown' | 'Alt+ArrowDown' | 'ArrowUp' | 'Alt+ArrowUp' | 'Home' | 'End' |
 *   'Enter' | 'Escape'} ListKey
 */

const KEYS = ['ArrowDown', 'ArrowUp', 'Home', 'End', 'Enter', 'Escape'];

/**
 * A key press as the list names it, or undefined for one it leaves to the box (a letter, Tab,
 * an Alt chord other than on the arrows, anything with Ctrl or Meta).
 * @param {{ key: string, altKey?: boolean, ctrlKey?: boolean, metaKey?: boolean }} e
 * @returns {ListKey | undefined}
 */
export function listKey(e) {
  if (e.ctrlKey || e.metaKey) return undefined;
  if (e.altKey && e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return undefined;
  if (!KEYS.includes(e.key)) return undefined;
  return /** @type {ListKey} */ (e.altKey ? `Alt+${e.key}` : e.key);
}

/**
 * What one key does to the list, over `count` options:
 *
 * | key            | closed                        | open                                  |
 * | -------------- | ----------------------------- | ------------------------------------- |
 * | ↓              | opens on the first            | the next, round to the first          |
 * | ↑              | opens on the last             | the previous, round to the last       |
 * | Alt+↓          | opens, none reached           | none reached                          |
 * | Alt+↑          | stays closed                  | closes                                |
 * | Home / End     | left to the caret             | the first / the last                  |
 * | Enter          | taken, picks nothing          | picks the one reached, closes         |
 * | Escape         | taken, nothing else           | closes, and goes no further           |
 *
 * `prevent`: the key is the list's (so the page doesn't act on it too); `stop`: Escape closed
 * the list, so a dialog around it stays open; `pick`: the option Enter picked, or -1.
 * @param {ListKey} key @param {ListState} s @param {number} count
 * @returns {{ state: ListState, prevent: boolean, stop: boolean, pick: number }}
 */
export function listAction(key, s, count) {
  const last = count - 1;
  const to = (/** @type {number} */ active, open = true) => ({ open, active });
  /** @type {ListState} */
  let state = s;
  switch (key) {
    case 'ArrowDown':
      state = count ? to(s.open && s.active >= 0 && s.active < last ? s.active + 1 : 0) : to(-1);
      break;
    case 'ArrowUp':
      state = count ? to(s.open && s.active > 0 ? s.active - 1 : last) : to(-1);
      break;
    case 'Alt+ArrowDown':
      state = to(-1);
      break;
    case 'Alt+ArrowUp':
      state = to(-1, false);
      break;
    case 'Home':
    case 'End':
      if (!s.open || !count) return { state: s, prevent: false, stop: false, pick: -1 };
      state = to(key === 'Home' ? 0 : last);
      break;
    case 'Enter':
      return {
        state: to(-1, false),
        prevent: true,
        stop: false,
        pick: s.open && s.active >= 0 && s.active < count ? s.active : -1,
      };
    case 'Escape':
      return { state: to(-1, false), prevent: true, stop: s.open, pick: -1 };
  }
  return { state, prevent: true, stop: false, pick: -1 };
}

/** A name compared as people mean it: trimmed, its accents composed, case aside. @param {string} t */
export const nameKey = (t) => t.trim().normalize('NFC').toLowerCase();

/**
 * The options that match what is typed, best first: the whole name, then its start, then the
 * start of a later word, then anywhere in it; within each, in the order given. Nothing typed
 * keeps every option, in order.
 * @template T
 * @param {readonly T[]} options @param {string} typed @param {(o: T) => string} label
 * @returns {T[]}
 */
export function matching(options, typed, label) {
  const q = nameKey(typed);
  if (!q) return [...options];
  /** @type {T[][]} */
  const ranks = [[], [], [], []];
  for (const o of options) {
    const name = nameKey(label(o));
    if (name === q) ranks[0].push(o);
    else if (name.startsWith(q)) ranks[1].push(o);
    else if (name.split(/[\s\-–/·,.]+/).slice(1).some((w) => w.startsWith(q))) ranks[2].push(o);
    else if (name.includes(q)) ranks[3].push(o);
  }
  return ranks.flat();
}
