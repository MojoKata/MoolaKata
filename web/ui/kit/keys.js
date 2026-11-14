// Home and End in anything typed into (requirements S12.18.13), a note's text too: the start and end of the line,
// as drawn, on every platform. A Mac's browsers read them as the page's top and bottom, and in
// a field that scrolls without moving the caret.

/**
 * Where Home or End moves a field's caret: back or forward, to the line's end or (with Ctrl or
 * Cmd, in text of several lines) the text's, the selection extended with Shift. Any other key,
 * or one with Alt, is not this.
 * @param {{ key: string, shiftKey?: boolean, ctrlKey?: boolean, metaKey?: boolean,
 *   altKey?: boolean }} e
 * @param {boolean} lines  whether the field holds several lines (a textarea)
 * @returns {{ dir: 'backward' | 'forward', by: 'lineboundary' | 'documentboundary',
 *   extend: boolean } | null}
 */
export function homeEnd(e, lines) {
  if ((e.key !== 'Home' && e.key !== 'End') || e.altKey) return null;
  return {
    dir: e.key === 'Home' ? 'backward' : 'forward',
    by: lines && (e.ctrlKey || e.metaKey) ? 'documentboundary' : 'lineboundary',
    extend: !!e.shiftKey,
  };
}

/**
 * The selection a move leaves where the browser can't move by drawn lines: the line runs
 * between line breaks. The end that moves is the selection's focus; with `extend` the other
 * stays.
 * @param {string} text
 * @param {number} start @param {number} end
 * @param {'forward' | 'backward' | 'none'} direction
 * @param {NonNullable<ReturnType<typeof homeEnd>>} m
 * @returns {[number, number, 'forward' | 'backward']}
 */
export function moved(text, start, end, direction, m) {
  const backward = direction === 'backward';
  const focus = backward ? start : end;
  const anchor = backward ? end : start;
  const to = m.by === 'documentboundary'
    ? (m.dir === 'backward' ? 0 : text.length)
    : m.dir === 'backward'
    ? text.lastIndexOf('\n', focus - 1) + 1
    : (text.indexOf('\n', focus) + 1 || text.length + 1) - 1;
  if (!m.extend) return [to, to, 'forward'];
  return to < anchor ? [to, anchor, 'backward'] : [anchor, to, 'forward'];
}

/** Whether an element is something typed into, with a caret. @param {EventTarget | null} el */
function typedInto(el) {
  if (el instanceof HTMLTextAreaElement) return true;
  if (!(el instanceof HTMLInputElement)) return false;
  try {
    return el.selectionStart !== null;
  } catch {
    return false;
  }
}

/**
 * Installed once, on the document: Home and End in any input or textarea move its caret, after
 * whatever drew the field has had the key (an open list's Home and End are its own).
 */
export function homeEndInText() {
  document.addEventListener('keydown', (e) => {
    const el = e.target;
    if (e.defaultPrevented) return;
    // A note's text, written in place: the browser moves by its drawn lines, or the key is left.
    if (el instanceof HTMLElement && el.isContentEditable) {
      const m = homeEnd(e, true);
      const sel = getSelection();
      if (!m || !sel || typeof sel.modify !== 'function') return;
      e.preventDefault();
      sel.modify(m.extend ? 'extend' : 'move', m.dir, m.by);
      return;
    }
    if (!typedInto(el)) return;
    const field = /** @type {HTMLInputElement | HTMLTextAreaElement} */ (el);
    const m = homeEnd(e, field instanceof HTMLTextAreaElement);
    if (!m) return;
    e.preventDefault();
    const sel = getSelection();
    if (sel && typeof sel.modify === 'function') {
      sel.modify(m.extend ? 'extend' : 'move', m.dir, m.by);
      return;
    }
    const [s, t, d] = moved(
      field.value,
      field.selectionStart ?? 0,
      field.selectionEnd ?? 0,
      field.selectionDirection ?? 'none',
      m,
    );
    field.setSelectionRange(s, t, d);
  });
}
