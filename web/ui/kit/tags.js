// Parts adapted from preact-components (MIT): see kit/NOTICE.md.
//
// Several of a list (requirements S12.18.12): each chosen item a chip with its own ×, and after
// them a box to type in, its matches listed below it. Where the list may grow (tags), a name that
// matches none is a new item; where it can't (people), it is refused. The field grows a row at a
// time to `maxRows` rows of chips and then scrolls; kept to one line, it scrolls sideways behind
// a count of the chips out of sight.
import { useLayoutEffect, useRef, useState } from 'preact/hooks';
import { html } from './html.js';
import { Icon } from './icon.js';
import { ReadValue, useReading } from './fields.js';
import { listAction, listKey, matching, nameKey } from './listbox.js';

/**
 * An item that may be chosen: its key (what the field holds), its name, and how often it is
 * used (listed first when typing).
 * @typedef {{ key: string, label: string, uses?: number }} Item
 */

/**
 * The names typed so far, split at commas: those before the last comma are finished, the rest
 * is still being typed. A paste of `a, b, c` and a keyboard that sends no key names both arrive
 * this way.
 * @param {string} text @returns {{ names: string[], rest: string }}
 */
export function splitNames(text) {
  const parts = text.split(',');
  const last = parts.pop() ?? '';
  return {
    names: parts.map((p) => p.trim()).filter(Boolean),
    rest: parts.length ? last.trimStart() : last,
  };
}

/**
 * What adding typed names comes to: each name, trimmed, is an item already there (case aside),
 * a new item where the list may grow, or refused. One already chosen, or typed twice, is left
 * out; the spelling chosen first is kept.
 * @param {readonly string[]} chosen keys @param {readonly Item[]} items
 * @param {readonly string[]} names @param {boolean} allowNew
 * @returns {{ keys: string[], made: string[], refused: string[] }} `keys` the field then holds;
 *   `made`, the names of new items to make (their keys are the caller's); `refused`, names
 *   matching nothing where none may be made
 */
export function addNames(chosen, items, names, allowNew) {
  const keys = [...chosen];
  const seen = new Set(
    keys.map((k) => nameKey(items.find((i) => i.key === k)?.label ?? k)),
  );
  /** @type {string[]} */
  const made = [], refused = [];
  for (const raw of names) {
    const name = raw.trim();
    if (!name) continue;
    const key = nameKey(name);
    if (seen.has(key)) continue;
    const item = items.find((i) => nameKey(i.label) === key);
    if (item) keys.push(item.key);
    else if (allowNew) made.push(name);
    else {
      refused.push(name);
      continue;
    }
    seen.add(key);
  }
  return { keys, made, refused };
}

/**
 * The options listed for what is typed: the items that match, those chosen left out, the most
 * used first where nothing is typed yet.
 * @param {readonly Item[]} items @param {readonly string[]} chosen @param {string} typed
 * @returns {Item[]}
 */
export function suggestions(items, chosen, typed) {
  const taken = new Set(chosen);
  const free = items.filter((i) => !taken.has(i.key));
  const byUse = typed.trim() ? free : [...free].sort((a, b) => (b.uses ?? 0) - (a.uses ?? 0));
  return matching(byUse, typed, (i) => i.label);
}

/**
 * What one key does in the box (the list's keys are `listAction`'s): a comma adds what is typed
 * and is never typed itself; Enter adds the option reached, or what is typed; Backspace in an
 * empty box takes off the last chip, but not one the key repeats while held. A key with Ctrl or
 * Meta is never the box's.
 * @param {{ key: string, altKey?: boolean, ctrlKey?: boolean, metaKey?: boolean, repeat?: boolean }} e
 * @param {import('./listbox.js').ListState} state @param {number} count @param {string} text
 * @returns {{ state: import('./listbox.js').ListState, prevent: boolean, stop: boolean,
 *   pick: number, commit: boolean, removeLast: boolean } | undefined}
 */
export function boxKey(e, state, count, text) {
  if (e.ctrlKey || e.metaKey) return undefined;
  const none = { pick: -1, commit: false, removeLast: false, stop: false };
  if (e.key === ',' && !e.altKey) {
    return { ...none, state: { open: false, active: -1 }, prevent: true, commit: true };
  }
  if (e.key === 'Backspace' && !e.altKey) {
    if (text !== '' || e.repeat) return undefined;
    return { ...none, state, prevent: true, removeLast: true };
  }
  const key = listKey(e);
  if (!key) return undefined;
  const a = listAction(key, state, count);
  if (key === 'Enter') {
    return { ...none, state: a.state, prevent: true, pick: a.pick, commit: a.pick < 0 };
  }
  return { ...none, state: a.state, prevent: a.prevent, stop: a.stop };
}

let seq = 0;

/**
 * The field. `value` holds the chosen items' keys, `items` every item that may be chosen.
 * `allowNew`: a name matching none is made, through `onCreate`, which gives its key. `noun`
 * names one item in what is said (*Remove work*, *3 tags before*). `autoGrow` (on unless false)
 * grows the field to `maxRows` rows of chips; off, it keeps to one line.
 * @param {{ value: readonly string[], items: readonly Item[],
 *   onChange: (keys: string[]) => void, allowNew?: boolean,
 *   onCreate?: (name: string) => string, noun?: [string, string], autoGrow?: boolean,
 *   maxRows?: number, placeholder?: string, id?: string, readonly?: boolean,
 *   disabled?: boolean, bad?: boolean, [k: string]: any }} p
 */
export function TagInput({
  value,
  items,
  onChange,
  allowNew = false,
  onCreate,
  noun = ['tag', 'tags'],
  autoGrow = true,
  maxRows = 3,
  placeholder,
  id,
  readonly,
  disabled,
  bad,
  ...rest
}) {
  const [text, setText] = useState('');
  const [state, setState] = useState(
    /** @type {import('./listbox.js').ListState} */ ({
      open: false,
      active: -1,
    }),
  );
  const [mark, setMark] = useState(/** @type {string | null} */ (null));
  const [said, setSaid] = useState('');
  const [before, setBefore] = useState(0);
  const wrap = useRef(/** @type {HTMLDivElement | null} */ (null));
  const box = useRef(/** @type {HTMLDivElement | null} */ (null));
  const input = useRef(/** @type {HTMLInputElement | null} */ (null));
  const own = useRef(`tags-${++seq}`);
  const base = id || own.current;
  const listId = `${base}-list`;
  const labelOf = (/** @type {string} */ k) => items.find((i) => i.key === k)?.label ?? k;
  const reading = useReading(readonly);

  const options = suggestions(items, value, text);
  const exact = text.trim() && items.some((i) => nameKey(i.label) === nameKey(text));
  const offerNew = allowNew && !!text.trim() && !exact;
  const count = options.length + (offerNew ? 1 : 0);

  // Kept to one line: the chips scrolled out of sight to the left, counted. The count is drawn
  // over the line, not in it, so showing it moves no chip and can't change what it counts.
  const recount = () => {
    const b = box.current;
    if (!b || autoGrow) return;
    const chips = /** @type {HTMLElement[]} */ ([...b.querySelectorAll('.tag')]);
    setBefore(chips.filter((c) => c.offsetLeft + c.offsetWidth / 2 < b.scrollLeft + 8).length);
  };
  // The box being typed in stays in view: at the end of one line (so at rest the count says
  // what is out of sight), at the bottom of the rows while it is being typed in.
  useLayoutEffect(() => {
    const b = box.current;
    if (!b) return;
    if (!autoGrow) b.scrollLeft = b.scrollWidth;
    else if (document.activeElement === input.current) b.scrollTop = b.scrollHeight;
    recount();
  }, [value.length, text, autoGrow]);

  if (reading) {
    const shown = value.map(labelOf).join(', ');
    return html`
      <${ReadValue} text=${shown || '—'} id=${id} aria-label=${rest['aria-label']}
        aria-describedby=${rest['aria-describedby']} data-help=${rest['data-help']} />
    `;
  }

  /** @param {string[]} keys @param {string} [what] */
  const change = (keys, what) => {
    onChange(keys);
    if (what) setSaid(what);
  };
  /** Add names as typed. @param {string[]} names */
  const add = (names) => {
    const r = addNames(value, items, names, allowNew);
    const keys = [...r.keys];
    for (const name of r.made) keys.push(onCreate ? onCreate(name) : name);
    if (r.refused.length) setMark('No match.');
    if (keys.length !== value.length) {
      const added = [...r.keys.slice(value.length).map(labelOf), ...r.made];
      change(keys, `Added ${added.join(', ')}`);
    }
    return r.refused.length === 0;
  };
  const commitText = () => {
    if (!text.trim()) return;
    if (add([text])) setText('');
  };
  /** An option picked: added, and the list stays open for the next. @param {number} i */
  const pick = (i) => {
    if (i < options.length) {
      change([...value, options[i].key], `Added ${options[i].label}`);
      setText('');
    } else commitText();
    setState({ open: true, active: -1 });
  };
  /** The chips, as elements. */
  const chipEls =
    () => /** @type {HTMLElement[]} */ ([...(box.current?.querySelectorAll('.tag') || [])]);
  /** The focus to a chip, or past the last, to the box. @param {number} i */
  const focusChip = (i) => {
    const el = chipEls()[i];
    if (el) {
      el.focus();
      el.scrollIntoView({ block: 'nearest', inline: 'nearest' });
    } else input.current?.focus();
  };
  /**
   * A chip taken off; the focus goes to `to` (a chip's place after it goes, or the box).
   * @param {number} i @param {number | null} [to]
   */
  const remove = (i, to = null) => {
    const gone = labelOf(value[i]);
    change(value.filter((_, j) => j !== i), `Removed ${gone}`);
    requestAnimationFrame(() => (to === null ? input.current?.focus() : focusChip(to)));
  };
  /** A chip's keys: the arrows move along the chips, Backspace and Delete take it off. */
  const chipKey = (/** @type {KeyboardEvent} */ e, /** @type {number} */ i) => {
    if (e.ctrlKey || e.metaKey || e.altKey || disabled) return;
    const last = value.length - 1;
    const to = {
      ArrowLeft: Math.max(0, i - 1),
      ArrowRight: i + 1,
      Home: 0,
      End: value.length,
    }[e.key];
    if (to !== undefined) {
      e.preventDefault();
      focusChip(to);
    } else if (e.key === 'Backspace') {
      e.preventDefault();
      remove(i, i > 0 ? i - 1 : last > 0 ? 0 : null);
    } else if (e.key === 'Delete') {
      e.preventDefault();
      remove(i, i < last ? i : null);
    }
  };

  const onKeyDown = (/** @type {KeyboardEvent} */ e) => {
    const el = /** @type {HTMLInputElement} */ (e.currentTarget);
    // ← at the start of the box goes on to the chips before it.
    if (
      e.key === 'ArrowLeft' && !e.altKey && !e.ctrlKey && !e.metaKey && !e.shiftKey &&
      el.selectionStart === 0 && el.selectionEnd === 0 && value.length
    ) {
      e.preventDefault();
      setState({ open: false, active: -1 });
      focusChip(value.length - 1);
      return;
    }
    const a = boxKey(e, state, count, text);
    if (!a) return;
    if (a.prevent) e.preventDefault();
    if (a.stop) e.stopPropagation();
    setState(a.state);
    if (a.removeLast && value.length) remove(value.length - 1);
    else if (a.pick >= 0) pick(a.pick);
    else if (a.commit) commitText();
  };
  const onInput = (/** @type {any} */ e) => {
    setMark(null);
    const { names, rest: left } = splitNames(e.currentTarget.value);
    if (names.length) {
      const ok = add(names);
      setText(ok ? left : e.currentTarget.value);
    } else setText(e.currentTarget.value);
    setState({ open: true, active: -1 });
  };
  /** Whether the focus is going somewhere else in the field. @param {FocusEvent} e */
  const within = (e) => !!wrap.current?.contains(/** @type {Node | null} */ (e.relatedTarget));
  const active = state.open && state.active >= 0 ? `${listId}-${state.active}` : undefined;
  const [one, many] = noun;
  return html`
    <div class="tag-wrap" ref=${wrap}>
      <div ref=${box} class=${'tag-box' + (autoGrow ? '' : ' one-line') +
        (bad || mark ? ' bad' : '') + (disabled ? ' off' : '')}
        style=${{ '--tag-rows': String(maxRows) }}
        onScroll=${recount}
        onMouseDown=${(/** @type {MouseEvent} */ e) => {
          if (e.target === e.currentTarget) {
            e.preventDefault();
            input.current?.focus();
          }
        }}>
        ${value.map((k, i) =>
          html`
            <span class="tag" key=${k} tabindex="-1" role="group" aria-label=${labelOf(k)}
              onKeyDown=${(/** @type {KeyboardEvent} */ e) => chipKey(e, i)}><span
                class="tag-name">${labelOf(k)}</span><button type="button" class="icon-btn"
                tabindex="-1" disabled=${disabled} aria-label=${`Remove ${labelOf(k)}`}
                data-tip=${`Remove ${labelOf(k)}`} onClick=${() => remove(i)}><${Icon}
                  name="x" /></button></span>
          `
        )}
        <input ...${rest} ref=${input} id=${id} type="text" role="combobox" autocomplete="off"
          aria-autocomplete="list" aria-expanded=${state.open && count > 0 ? 'true' : 'false'}
          aria-controls=${listId} aria-activedescendant=${active}
          aria-invalid=${bad || mark || rest['aria-invalid'] ? 'true' : undefined}
          aria-description=${mark || undefined} data-tip=${mark || undefined}
          disabled=${disabled} value=${text} placeholder=${value.length ? '' : placeholder}
          onInput=${onInput} onKeyDown=${onKeyDown}
          onFocus=${() => setState({ open: false, active: -1 })}
          onBlur=${(/** @type {FocusEvent} */ e) => {
            setState({ open: false, active: -1 });
            // Typed text becomes a chip when the field is left, not when a chip takes the focus.
            if (!within(e)) commitText();
          }} />
      </div>
      ${before
        ? html`
          <button type="button" class="before" tabindex="-1"
            aria-label=${`${before} ${before === 1 ? one : many} before`}
            data-tip=${`${before} ${before === 1 ? one : many} before`}
            onClick=${() => {
              if (box.current) box.current.scrollLeft = 0;
              focusChip(0);
            }}><${Icon} name="chev" />${before}</button>
        `
        : null}
      ${state.open && (count > 0 || (text.trim() && !allowNew))
        ? html`
          <ul class="tag-list" role="listbox" id=${listId} aria-label=${`Your ${many}`}>
            ${options.map((o, i) =>
              html`
                <li role="option" id=${`${listId}-${i}`} key=${o.key}
                  aria-selected=${state.active === i ? 'true' : 'false'}
                  onMouseDown=${(/** @type {MouseEvent} */ e) => {
                    e.preventDefault();
                    pick(i);
                  }}>${o.label}${o.uses != null
                    ? html`<span class="uses">${o.uses}</span>`
                    : null}</li>
              `
            )}
            ${offerNew
              ? html`
                <li role="option" id=${`${listId}-${options.length}`} class="new"
                  aria-selected=${state.active === options.length ? 'true' : 'false'}
                  onMouseDown=${(/** @type {MouseEvent} */ e) => {
                    e.preventDefault();
                    pick(options.length);
                  }}>${`Make the ${one} “${text.trim()}”`}</li>
              `
              : null}
            ${!count ? html`<li class="none" role="presentation">No match</li>` : null}
          </ul>
        `
        : null}
      <span class="sr-only" role="status" aria-live="polite">${said}</span>
    </div>
  `;
}
