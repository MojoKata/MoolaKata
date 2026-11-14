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
import { useFormats } from './formats.js';

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
 *   max?: string | null, today?: string, timezone?: string, id?: string, placeholder?: string,
 *   bad?: boolean, disabled?: boolean, [k: string]: any }} p
 */
export function DateInput(
  { value, onInput, min, max, today, timezone, id, placeholder, bad, disabled, ...rest },
) {
  const [typing, setTyping] = useState(/** @type {string | null} */ (null));
  const [open, setOpen] = useState(false);
  const wrap = useRef(/** @type {HTMLSpanElement | null} */ (null));
  const input = useRef(/** @type {HTMLInputElement | null} */ (null));
  // Today: as given, else in its time zone, its part of the page's, or the person's.
  const zoned = useFormats({ timezone }).today();
  const now = today || zoned;
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

/** `HH:MM` from minutes after midnight. @param {number} m */
const hm = (m) =>
  `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
/** Minutes after midnight from `HH:MM`. @param {string} t */
const minutes = (t) => Number(t.slice(0, 2)) * 60 + Number(t.slice(3));

/**
 * The hours a time picker shows: 7 AM to 6 PM, stretched to take in `at` (an hour, or null).
 * @param {number | null} at @returns {[number, number]}
 */
export function hoursShown(at) {
  return [Math.min(7, at ?? 7), Math.max(18, at ?? 18)];
}

/**
 * Where a key moves the picker's time, as minutes after midnight: ← → a quarter, ↑ ↓ an hour,
 * Page Up and Page Down three hours, Home and End to the hour's :00 and :45; held within the
 * day. Undefined for a key it doesn't move on.
 * @param {number} m @param {string} key
 */
export function moveTime(m, key) {
  const to = {
    ArrowLeft: m - 15,
    ArrowRight: m + 15,
    ArrowUp: m - 60,
    ArrowDown: m + 60,
    PageUp: m - 180,
    PageDown: m + 180,
    Home: m - (m % 60),
    End: m - (m % 60) + 45,
  }[key];
  return to === undefined ? undefined : Math.min(23 * 60 + 45, Math.max(0, to));
}

/**
 * The hours each field's picker shows, kept while the page is open (not across loads): a picker
 * opened again shows what it showed when it closed, by the field's id.
 * @type {Map<string, [number, number]>}
 */
const shownBefore = new Map();
let timeFields = 0;

/**
 * The times of day by the quarter hour (S12.18.11): a row an hour, its :00 and :30 bold, under
 * AM and PM; 7 AM to 6 PM at first (or what this field's picker last showed), three hours more
 * each way from the chevrons at its corners, until midnight and 11 PM are in it; as tall as 7 AM
 * to 6 PM, scrolling once more is shown. The field's time is marked (a time between quarters
 * marks the quarter before it, outlined) and is the grid's Tab stop; the keys of `moveTime`
 * move it, showing more hours as they go past those shown; Enter picks, Escape closes.
 * @param {{ value: string | null, onPick: (hm: string) => void, onClose: () => void,
 *   memo?: string }} p
 */
export function TimePicker({ value, onPick, onClose, memo }) {
  const at = value && /^\d{2}:\d{2}$/.test(value) ? minutes(value) : null;
  const near = at === null ? null : at - (at % 15);
  const [[from, to], setShown] = useState(() => {
    const [f, t] = hoursShown(at === null ? null : Math.floor(at / 60));
    const was = memo ? shownBefore.get(memo) : undefined;
    return /** @type {[number, number]} */ (was
      ? [Math.min(f, was[0]), Math.max(t, was[1])]
      : [f, t]);
  });
  const [focus, setFocus] = useState(() => near ?? 7 * 60);
  const grid = useRef(/** @type {HTMLDivElement | null} */ (null));
  const scroller = useRef(/** @type {HTMLDivElement | null} */ (null));
  const reveal = useRef(/** @type {'top' | 'bottom' | null} */ (null));
  /** @param {[number, number]} hours @param {'top' | 'bottom' | null} [show] */
  const setHours = (hours, show = null) => {
    if (memo) shownBefore.set(memo, hours);
    reveal.current = show;
    setShown(hours);
  };
  useLayoutEffect(() => {
    /** @type {HTMLElement | null | undefined} */ (grid.current?.querySelector(
      `[data-time="${hm(focus)}"]`,
    ))?.focus({ preventScroll: true });
    const sc = scroller.current;
    const cell = grid.current?.querySelector(`[data-time="${hm(focus)}"]`);
    if (sc && reveal.current === 'top') sc.scrollTop = 0;
    else if (sc && reveal.current === 'bottom') sc.scrollTop = sc.scrollHeight;
    else cell?.scrollIntoView({ block: 'nearest' });
    reveal.current = null;
  }, [focus, from, to]);
  /** The focus to a time, the hours shown stretched to it three at a time. @param {number} m */
  const go = (m) => {
    const h = Math.floor(m / 60);
    if (h < from) setHours([Math.max(0, Math.min(h, from - 3)), to]);
    if (h > to) setHours([from, Math.min(23, Math.max(h, to + 3))]);
    setFocus(m);
  };
  const onKeyDown = (/** @type {KeyboardEvent} */ e) => {
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      onClose();
      return;
    }
    if (e.key === 'Enter' || e.key === ' ') {
      const t = /** @type {HTMLElement} */ (e.target).dataset?.time;
      if (t) {
        e.preventDefault();
        onPick(t);
      }
      return;
    }
    const m = moveTime(focus, e.key);
    if (m === undefined) return;
    e.preventDefault();
    go(m);
  };
  const rows = [];
  for (let h = from; h <= to; h++) {
    if (h === from || h === 12) {
      rows.push(
        html`<div class="time-half" key=${h < 12 ? 'am' : 'pm'} aria-hidden="true">${
          h < 12 ? 'AM' : 'PM'
        }</div>`,
      );
    }
    const label = `${h % 12 || 12}`;
    rows.push(html`<div class="time-row" role="row" key=${h}>${
      [0, 15, 30, 45].map((q, i) => {
        const m = h * 60 + q;
        const t = hm(m);
        const half = h < 12 ? 'AM' : 'PM';
        const on = m === at, nearly = !on && m === near;
        return html`
          ${i
            ? html`<span class="sep" aria-hidden="true">·</span>`
            : null}<button type="button" role="gridcell" data-time=${t}
            class=${'time-q' + (q % 30 ? '' : ' bold') + (q ? '' : ' hour') + (on ? ' on' : '') +
              (nearly ? ' near' : '')}
            tabindex=${m === focus ? '0' : '-1'} aria-selected=${on || nearly ? 'true' : 'false'}
            aria-label=${`${label}:${String(q).padStart(2, '0')} ${half}`}
            onClick=${() => onPick(t)}>${q ? `:${q}` : `${label}:00`}</button>
        `;
      })
    }</div>`);
  }
  /** A chevron at a corner. @param {'up' | 'down'} way */
  const more = (way) =>
    html`
      <button type="button" class=${'icon-btn time-more ' + way} tabindex="-1"
        aria-label=${way === 'up' ? 'Earlier times' : 'Later times'}
        data-tip=${way === 'up' ? 'Earlier times' : 'Later times'}
        onMouseDown=${(/** @type {MouseEvent} */ e) => e.preventDefault()}
        onClick=${() =>
          way === 'up'
            ? setHours([Math.max(0, from - 3), to], 'top')
            : setHours([from, Math.min(23, to + 3)], 'bottom')}><${Icon}
              name=${way === 'up' ? 'chevs-up' : 'chevs-down'} /></button>
    `;
  return html`
    <div class="time-pop" role="dialog" aria-label="Choose a time" onKeyDown=${onKeyDown}>
      <div class="time-scroll" ref=${scroller}>
        <div class="time-grid" role="grid" aria-label="Times of day" ref=${grid}>${rows}</div>
      </div>
      ${from > 0 ? more('up') : null}${to < 23 ? more('down') : null}
    </div>
  `;
}

/**
 * A time-of-day field: it reads `5:30 PM` at rest; in it, a time may be typed as people write
 * it (`5:30p`, `17:30`, `noon`), or picked by the quarter hour from the picker its clock button
 * or ↓ opens (`TimePicker`); the focus comes back to the field when it closes. `onInput` hears
 * it as `HH:MM` as soon as it reads as one.
 * @param {{ value: string | null | undefined, onInput: (v: string) => void, id?: string,
 *   placeholder?: string, bad?: boolean, disabled?: boolean, [k: string]: any }} p
 */
export function TimeInput({ value, onInput, id, placeholder, bad, disabled, ...rest }) {
  const [typing, setTyping] = useState(/** @type {string | null} */ (null));
  const own = useRef(`time-${++timeFields}`);
  const [open, setOpen] = useState(false);
  const wrap = useRef(/** @type {HTMLSpanElement | null} */ (null));
  const input = useRef(/** @type {HTMLInputElement | null} */ (null));
  const v = String(value ?? '');
  const shown = typing ?? (/^\d{2}:\d{2}$/.test(v) ? timeText(v) : v);
  useEffect(() => {
    if (!open) return;
    // A click outside closes the picker.
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
      // Tab past the picker closes it.
      if (open && !wrap.current?.contains(/** @type {Node | null} */ (e.relatedTarget))) {
        setOpen(false);
      }
    }}>
      <input ref=${input} class=${'in' + (bad ? ' bad' : '')} type="text" id=${id}
        value=${shown} placeholder=${placeholder ?? 'ex: 5:30 PM'} autocomplete="off"
        disabled=${disabled} aria-haspopup="dialog" aria-expanded=${open ? 'true' : 'false'}
        onInput=${(/** @type {any} */ e) => {
          const t = e.currentTarget.value;
          setTyping(t);
          onInput(readTime(t) ?? t);
        }}
        onKeyDown=${(/** @type {KeyboardEvent} */ e) => {
          if (e.key === 'ArrowDown' && !e.ctrlKey && !e.metaKey) {
            e.preventDefault();
            setOpen(true);
            return;
          }
          onKeyDown?.(e);
        }}
        onBlur=${(/** @type {any} */ e) => {
          if (typing !== null) {
            const read = readTime(typing);
            setTyping(null);
            if (read) e.currentTarget.value = timeText(read);
          }
          onBlur?.(e);
        }} ...${pass} />
      <button type="button" class="icon-btn" tabindex="-1" disabled=${disabled}
        aria-label="Choose a time" data-tip="Choose a time (↓)"
        onClick=${() => setOpen(!open)}><${Icon} name="clock" /></button>
      ${open
        ? html`
          <${TimePicker} value=${readTime(shown) ?? (/^\d{2}:\d{2}$/.test(v) ? v : null)}
            memo=${id || own.current} onClose=${close} onPick=${(/** @type {string} */ t) => {
              setTyping(null);
              onInput(t);
              close();
            }} />
        `
        : null}
    </span>
  `;
}
