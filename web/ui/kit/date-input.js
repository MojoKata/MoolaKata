// A date typed as people write it, with a month's calendar under it (requirements S12.18.10),
// and a time of day typed the same way (S12.18.11). Each holds its value as text, as a record's
// field does: a date `YYYY-MM-DD`, a time `HH:MM`, or what was typed while it isn't one yet,
// which the field's check marks when it is left.
import { useEffect, useLayoutEffect, useRef, useState } from 'preact/hooks';
import { html } from './html.js';
import { Icon } from './icon.js';
import {
  dateText,
  monthGrid,
  MONTHS,
  moveDay,
  outside,
  partsOf,
  readDate,
  readTime,
  timeText,
  within,
} from './dates.js';
import { today as todayInZone } from './format.js';
import { listAction, listKey } from './listbox.js';

const WEEKDAYS = [
  ['Su', 'Sunday'],
  ['Mo', 'Monday'],
  ['Tu', 'Tuesday'],
  ['We', 'Wednesday'],
  ['Th', 'Thursday'],
  ['Fr', 'Friday'],
  ['Sa', 'Saturday'],
];

/**
 * A month of days (S12.18.10.1): six weeks, the picked day and today marked, days outside the
 * bounds off. The arrows move a day or a week, Page Up and Page Down a month, Home and End to
 * the week's ends; Enter or a click picks, Escape closes. One day is the grid's Tab stop.
 * @param {{ value: string | null, today: string, min?: string | null, max?: string | null,
 *   onPick: (iso: string) => void, onClose: () => void, label?: string }} p
 */
export function Calendar({ value, today, min, max, onPick, onClose, label = 'Choose a date' }) {
  const [at, setAt] = useState(() => within(value || today, min, max));
  const grid = useRef(/** @type {HTMLDivElement | null} */ (null));
  const [y, m] = partsOf(at);
  const cells = monthGrid(y, m);
  useLayoutEffect(() => {
    /** @type {HTMLElement | null | undefined} */ (grid.current?.querySelector(
      `[data-day="${at}"]`,
    ))
      ?.focus();
  }, [at]);
  /** @param {number} n */
  const month = (n) => {
    const k = y * 12 + (m - 1) + n;
    const first = `${String(Math.floor(k / 12)).padStart(4, '0')}-${
      String((k % 12) + 1).padStart(2, '0')
    }-01`;
    setAt(within(first, min, max));
  };
  const onKeyDown = (/** @type {KeyboardEvent} */ e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key === 'Enter' || e.key === ' ') {
      const day = /** @type {HTMLElement} */ (e.target).dataset?.day;
      if (day) {
        e.preventDefault();
        if (!outside(day, min, max)) onPick(day);
      }
      return;
    }
    const to = moveDay(at, e);
    if (!to) return;
    e.preventDefault();
    setAt(within(to, min, max));
  };
  const rows = Array.from({ length: 6 }, (_, r) => cells.slice(r * 7, r * 7 + 7));
  return html`
    <div class="cal-pop" role="dialog" aria-label=${label} onKeyDown=${onKeyDown}>
      <div class="cal-head">
        <button type="button" class="icon-btn" aria-label="Previous month"
          data-tip="Previous month (Page Up)" onClick=${() =>
            month(-1)}><${Icon} name="chev" /></button>
        <b aria-live="polite">${MONTHS[m - 1]} ${y}</b>
        <button type="button" class="icon-btn next" aria-label="Next month"
          data-tip="Next month (Page Down)" onClick=${() =>
            month(1)}><${Icon} name="chev" /></button>
      </div>
      <div class="cal-grid" role="grid" ref=${grid} aria-label=${`${MONTHS[m - 1]} ${y}`}>
        <div class="cal-row" role="row">${WEEKDAYS.map(([s, l]) =>
          html`<span class="wd" role="columnheader" aria-label=${l}>${s}</span>`
        )}</div>
        ${rows.map((row) =>
          html`<div class="cal-row" role="row">${
            row.map((d) => {
              if (!d) return html`<span class="out" role="gridcell"></span>`;
              const off = !!outside(d, min, max);
              return html`
                <button type="button" role="gridcell" data-day=${d}
                  class=${(d === value ? 'on' : '') + (d === today ? ' today' : '')}
                  tabindex=${d === at ? '0' : '-1'} aria-selected=${d === value ? 'true' : 'false'}
                  aria-current=${d === today ? 'date' : undefined} aria-disabled=${off
                    ? 'true'
                    : undefined} aria-label=${dateText(d)}
                  onClick=${() => off || onPick(d)}>${partsOf(d)[2]}</button>
              `;
            })
          }</div>`
        )}
      </div>
    </div>
  `;
}

/**
 * A date field: it reads `Oct 12, 2026` at rest; in it, a date may be typed as people write it
 * (`10/12`, `oct 12`, `today`). The button at its right end, ↓, or Alt+↓ opens the calendar;
 * the focus comes back to the field when it closes. `onInput` hears the date as `YYYY-MM-DD`
 * as soon as what is typed reads as one, else what is typed.
 * @param {{ value: string | null | undefined, onInput: (v: string) => void, min?: string | null,
 *   max?: string | null, today?: string, id?: string, placeholder?: string, bad?: boolean,
 *   disabled?: boolean, [k: string]: any }} p
 */
export function DateInput(
  { value, onInput, min, max, today, id, placeholder, bad, disabled, ...rest },
) {
  const [typing, setTyping] = useState(/** @type {string | null} */ (null));
  const [open, setOpen] = useState(false);
  const wrap = useRef(/** @type {HTMLSpanElement | null} */ (null));
  const input = useRef(/** @type {HTMLInputElement | null} */ (null));
  const now = today || todayInZone();
  const v = String(value ?? '');
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(v) ? v : null;
  const shown = typing ?? (iso ? dateText(iso) : v);
  useEffect(() => {
    if (!open) return;
    // A click outside closes the calendar.
    const away = (/** @type {MouseEvent} */ e) => {
      if (!wrap.current?.contains(/** @type {Node} */ (e.target))) setOpen(false);
    };
    document.addEventListener('mousedown', away);
    return () => document.removeEventListener('mousedown', away);
  }, [open]);
  const close = () => {
    setOpen(false);
    input.current?.focus();
  };
  const { onBlur, onKeyDown, onInput: _drop, ...pass } = rest;
  return html`
    <span class="date-in" ref=${wrap} onFocusOut=${(/** @type {FocusEvent} */ e) => {
      // Tab past the calendar closes it.
      if (open && !wrap.current?.contains(/** @type {Node | null} */ (e.relatedTarget))) {
        setOpen(false);
      }
    }}>
      <input ref=${input} class=${'in' + (bad ? ' bad' : '')} type="text" id=${id}
        value=${shown} placeholder=${placeholder ?? 'ex: 10/12/2026'} disabled=${disabled}
        autocomplete="off" aria-haspopup="dialog" aria-expanded=${open ? 'true' : 'false'}
        onInput=${(/** @type {any} */ e) => {
          const t = e.currentTarget.value;
          setTyping(t);
          onInput(readDate(t, now) ?? t);
        }}
        onBlur=${(/** @type {any} */ e) => {
          if (typing !== null) {
            const read = readDate(typing, now);
            setTyping(null);
            if (read) e.currentTarget.value = dateText(read);
          }
          onBlur?.(e);
        }}
        onKeyDown=${(/** @type {KeyboardEvent} */ e) => {
          if (e.key === 'ArrowDown' && !e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            setOpen(true);
            return;
          }
          onKeyDown?.(e);
        }} ...${pass} />
      <button type="button" class="icon-btn" tabindex="-1" disabled=${disabled}
        aria-label="Open the calendar" data-tip="Open the calendar (↓)"
        onClick=${() => setOpen(!open)}><${Icon} name="calendar" /></button>
      ${open
        ? html`
          <${Calendar} value=${readDate(shown, now) ?? iso} today=${now} min=${min} max=${max}
            onClose=${close}
            onPick=${(/** @type {string} */ d) => {
              setTyping(null);
              onInput(d);
              close();
            }} />
        `
        : null}
    </span>
  `;
}

/** The times of day a list offers, every `step` minutes: `00:00`, `00:15`, … @param {number} step */
export function timesOfDay(step) {
  const out = [];
  for (let m = 0; m < 24 * 60; m += step) {
    out.push(`${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`);
  }
  return out;
}

/**
 * A time-of-day field: it reads `5:30 PM` at rest; in it, a time may be typed as people write
 * it (`5:30p`, `17:30`, `noon`), or picked from the times of day every `step` minutes, which its
 * clock button or ↓ lists, on the field's time. `onInput` hears it as `HH:MM` as soon as it
 * reads as one.
 * @param {{ value: string | null | undefined, onInput: (v: string) => void, id?: string,
 *   placeholder?: string, bad?: boolean, step?: number, disabled?: boolean, [k: string]: any }} p
 */
export function TimeInput({ value, onInput, id, placeholder, bad, step = 15, disabled, ...rest }) {
  const [typing, setTyping] = useState(/** @type {string | null} */ (null));
  const [list, setList] = useState(
    /** @type {import('./listbox.js').ListState} */ ({
      open: false,
      active: -1,
    }),
  );
  const wrap = useRef(/** @type {HTMLSpanElement | null} */ (null));
  const input = useRef(/** @type {HTMLInputElement | null} */ (null));
  const v = String(value ?? '');
  const shown = typing ?? (/^\d{2}:\d{2}$/.test(v) ? timeText(v) : v);
  const times = timesOfDay(step);
  const listId = `${id || 'time'}-times`;
  useLayoutEffect(() => {
    if (!list.open) return;
    wrap.current?.querySelector(`#${CSS.escape(`${listId}-${list.active}`)}`)
      ?.scrollIntoView({ block: 'nearest' });
  }, [list.open, list.active]);
  /** The list, open on the field's time or the next on the list. */
  const openList = () => {
    const at = readTime(shown) ?? '';
    const i = times.findIndex((t) => t >= at);
    setList({ open: true, active: at ? (i < 0 ? times.length - 1 : i) : 0 });
  };
  /** @param {number} i */
  const pick = (i) => {
    setTyping(null);
    onInput(times[i]);
    setList({ open: false, active: -1 });
    input.current?.focus();
  };
  const { onBlur, onKeyDown, onInput: _drop, ...pass } = rest;
  return html`
    <span class="date-in" ref=${wrap}>
      <input ref=${input} class=${'in' + (bad ? ' bad' : '')} type="text" id=${id}
        value=${shown} placeholder=${placeholder ?? 'ex: 5:30 PM'} autocomplete="off"
        disabled=${disabled} role="combobox" aria-autocomplete="none"
        aria-expanded=${list.open ? 'true' : 'false'} aria-controls=${listId}
        aria-activedescendant=${list.open && list.active >= 0
          ? `${listId}-${list.active}`
          : undefined}
        onInput=${(/** @type {any} */ e) => {
          const t = e.currentTarget.value;
          setTyping(t);
          onInput(readTime(t) ?? t);
        }}
        onKeyDown=${(/** @type {KeyboardEvent} */ e) => {
          const key = listKey(e);
          if (!list.open) {
            if (key === 'ArrowDown' || key === 'Alt+ArrowDown') {
              e.preventDefault();
              openList();
              return;
            }
            onKeyDown?.(e);
            return;
          }
          if (!key) return;
          const a = listAction(key, list, times.length);
          if (a.prevent) e.preventDefault();
          if (a.stop) e.stopPropagation();
          if (a.pick >= 0) pick(a.pick);
          else setList(a.state);
        }}
        onBlur=${(/** @type {any} */ e) => {
          if (!wrap.current?.contains(e.relatedTarget)) setList({ open: false, active: -1 });
          if (typing !== null) {
            const read = readTime(typing);
            setTyping(null);
            if (read) e.currentTarget.value = timeText(read);
          }
          onBlur?.(e);
        }} ...${pass} />
      <button type="button" class="icon-btn" tabindex="-1" disabled=${disabled}
        aria-label="List the times" data-tip="List the times (↓)"
        onMouseDown=${(/** @type {MouseEvent} */ e) => e.preventDefault()}
        onClick=${() => {
          input.current?.focus();
          if (list.open) setList({ open: false, active: -1 });
          else openList();
        }}><${Icon} name="clock" /></button>
      ${list.open
        ? html`
          <ul class="tag-list time-list" role="listbox" id=${listId} aria-label="Times of day">
            ${times.map((t, i) =>
              html`
                <li role="option" id=${`${listId}-${i}`} key=${t}
                  aria-selected=${list.active === i ? 'true' : 'false'}
                  onMouseDown=${(/** @type {MouseEvent} */ e) => {
                    e.preventDefault();
                    pick(i);
                  }}>${timeText(t)}</li>
              `
            )}
          </ul>
        `
        : null}
    </span>
  `;
}
