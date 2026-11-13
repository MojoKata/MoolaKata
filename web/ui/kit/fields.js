// Form fields: a label, the control, a hint and the server's refusal at that field (R3.7).
// Each control's id is "f-" and its label's slug, which the help pane follows (S12.7.3).
import { cloneElement, createContext, isValidElement } from 'preact';
import { useContext, useRef, useState } from 'preact/hooks';
import { html } from './html.js';
import { slug } from './format.js';
import { Icon } from './icon.js';
import { accepts, check, cleanPaste, kindOf, readText, says } from './kinds.js';
import { hideTip, showTip } from './tooltip.js';
import {
  padded,
  shownText,
  textOf,
  typeNatural,
  typeRegister,
  ungroup,
  valueOf,
} from './numbers.js';
import { DateInput, TimeInput } from './date-input.js';

/**
 * The page of the record an id names, or null: a list of references reads as a link to the
 * chosen record's page (S12.18.6.2). The app says how, once, with `linkRecords`.
 * @type {(id: any) => string | null}
 */
let pageOf = () => null;
/** @param {(id: any) => string | null} fn */
export function linkRecords(fn) {
  pageOf = fn;
}

/** What a dialog opened over another puts before its fields' ids ("d1-"), so they stay its own
 * (S12.15.7); the help pane reads past it. */
export const IdPrefix = createContext('');

/**
 * Whether the fields inside draw their read persona (S12.18.6): a form or dialog shown to one
 * who can only read sets it once, and every input in it reads; its value is why, when it
 * isn't *Shared with you to read*. A control's own `readonly` wins over it.
 */
export const Reading = createContext(/** @type {boolean | string} */ (false));

/** Whether a control reads: its own `readonly`, else its form's. @param {boolean | undefined} own */
export function useReading(own) {
  const form = useContext(Reading);
  return own ?? !!form;
}

/**
 * A value in the read persona (S12.18.6): the edit control's box, unframed, its text where the
 * control's text would be, so nothing moves when a form flips between the two. Reached by Tab,
 * so the help pane follows it; named by its field's label. `href` makes it a link (a record's
 * page, a web address); `select` keeps a list's chevron space, `rows` a text box's height.
 * @param {{ text: string, href?: string | null, external?: boolean, select?: boolean,
 *   rows?: number, id?: string, style?: any, [k: string]: any }} p
 */
export function ReadValue({ text, href, external, select, rows, id, style, ...rest }) {
  const blank = text === '—';
  const cls = 'in read' + (select ? ' select' : '') + (rows ? ' multi' : '') +
    (blank ? ' blank' : '');
  const named = {
    'aria-label': rest['aria-label'],
    'aria-labelledby': rest['aria-label'] || !id ? undefined : 'lbl-' + id,
    'aria-describedby': rest['aria-describedby'],
    'data-help': rest['data-help'],
  };
  if (href && !blank) {
    return html`<span class=${cls} style=${style}><a id=${id} href=${href} ...${named}
      target=${external ? '_blank' : undefined} rel=${
      external ? 'noopener noreferrer' : undefined
    }>${text}</a></span>`;
  }
  return html`
    <span class=${cls} id=${id} role="textbox" aria-readonly="true"
      aria-multiline=${rows ? 'true' : undefined} tabindex="0" style=${{
        ...(style || {}),
        ...(rows ? { minHeight: `calc(${rows} * 1.5em + 18px)` } : {}),
      }} ...${named}>${text}</span>
  `;
}

/**
 * @param {{ label: string, id?: string, hint?: any, error?: string | null, help?: string,
 *   children: any }} p
 */
export function Field({ label, id, hint, error, help, children }) {
  // A control that repeats (a split's parts) keeps a unique id and names its heading with
  // data-help instead (S12.7.3).
  const fid = useContext(IdPrefix) + (help ? 'x-' : 'f-') + (id || slug(label));
  const kids = Array.isArray(children) ? children : [children];
  const control = kids.map((c) =>
    isValidElement(c) && !(/** @type {any} */ (c).props.id)
      ? cloneElement(/** @type {any} */ (c), {
        id: fid,
        'data-help': help,
        'aria-invalid': error ? 'true' : undefined,
        'aria-describedby': error ? fid + '-err' : undefined,
      })
      : c
  );
  return html`<div class="field">
    <label for=${fid} id=${'lbl-' + fid}>${label}</label>
    ${control}
    ${hint ? html`<div class="hint">${hint}</div>` : null}
    ${error ? html`<div class="err" id=${fid + '-err'} role="alert">${error}</div>` : null}
  </div>`;
}

/**
 * A text input bound to a value. A password input carries an eye button that shows what was
 * typed and hides it again (S12.1.3); so does a `secret`, a secret that isn't the person's own
 * sign-in, drawn blurred rather than as a password, so a password manager leaves it alone. `prefix` and `suffix` are a unit shown in the field
 * (S12.18.9); `num` sets its text at the right, as a number's is.
 * @param {{ value: any, onInput: (v: string) => void, type?: string, placeholder?: string,
 *   bad?: boolean, autocomplete?: string, id?: string, inputmode?: string, required?: boolean,
 *   readonly?: boolean, prefix?: string, suffix?: string, num?: boolean, [k: string]: any }} p
 */
export function Input(
  { value, onInput, type = 'text', placeholder, bad, readonly, prefix, suffix, num, ...rest },
) {
  const [shown, setShown] = useState(false);
  const secret = type === 'secret';
  if (useReading(readonly)) {
    const v = String(value ?? '');
    return html`
      <${ReadValue} text=${v === '' ? '—' : type === 'password' || secret ? '••••••••' : v}
        ...${rest} />
    `;
  }
  // A secret that isn't the person's own sign-in (a recovery phrase, an API key, a bank's
  // password) is plain text drawn blurred: a password manager offers nothing for it, and fills
  // nothing into it (S12.1.3).
  const keep = secret
    ? {
      autocomplete: 'off',
      spellcheck: false,
      autocapitalize: 'off',
      'data-1p-ignore': 'true',
      'data-lpignore': 'true',
      'data-bwignore': 'true',
      'data-form-type': 'other',
    }
    : {};
  const input = html`
    <input class=${'in' + (bad ? ' bad' : '') + (num ? ' num' : '') +
      (secret && !shown ? ' veiled' : '')} type=${type === 'password' && !shown
      ? 'password'
      : secret || type === 'password'
      ? 'text'
      : type} value=${value ?? ''} ...${keep}
      placeholder=${placeholder} onInput=${(/** @type {any} */ e) => onInput(e.currentTarget.value)}
      ...${rest} />
  `;
  if (prefix || suffix) {
    // A unit in the field (S12.18.9): neither typed nor stored; a click on it is the field's.
    return html`
      <span class=${'unit-in' + (prefix ? ' pre' : '') + (suffix ? ' post' : '')}
        style=${suffix ? { '--unit-w': `${String(suffix).length + 2}ch` } : undefined}>${prefix
          ? html`<span class="unit pre" aria-hidden="true">${prefix}</span>`
          : null}${input}${suffix
          ? html`<span class="unit post" aria-hidden="true">${suffix}</span>`
          : null}</span>
    `;
  }
  if (type !== 'password' && !secret) return input;
  const what = secret ? 'it' : 'password';
  return html`<span class="pw">${input}<button type="button" class="icon-btn"
    aria-label=${shown ? `Hide ${what}` : `Show ${what}`} aria-pressed=${shown ? 'true' : 'false'}
    onClick=${() => setShown(!shown)}><${Icon} name=${
    shown ? 'eye-off' : 'eye'
  } /></button></span>`;
}

/**
 * @typedef {{ text: string, value: string, label: string }} Fill
 * A value a button fills in: its word, the value, and its name, which is its tooltip and what a
 * screen reader says ("Use last year's: 4,200.00").
 */

/**
 * A field whose special values are controls that fill it in, never meanings of a blank or a 0
 * (R3.11). Inside it, at its end, × clears it (`clear`), while it holds something. Under it, at
 * its right, a row of words that read as links: **min** (from `min`; an amount only, a
 * count's least being quicker typed), **default** (`reset`), **max** (from `max`), or **all**
 * for a count (`noun` given), then any other value in `fill`, a dot between each. Each names its
 * value as its tooltip and to a screen reader ("Min: $0.00", "Use the default: 30 days",
 * "All: 2 contracts"; `format` shows it as the field does), and is off, greyed, while the field
 * holds its value. It draws the controls only: `<TypedInput>` checks what is typed.
 * @param {{ value: string, onInput: (v: string) => void, clear?: boolean,
 *   reset?: { value: string, label: string }, min?: number | string, max?: number | string,
 *   noun?: string, format?: (n: any) => string, fill?: Fill[], id?: string,
 *   inputmode?: string, type?: string, placeholder?: string, bad?: boolean, [k: string]: any }} p
 */
export function ValueInput(
  { value, onInput, clear, reset, min, max, noun, format = String, fill = [], bad, ...rest },
) {
  const v = value ?? '';
  const words = /** @type {Fill[]} */ ([
    min != null && !noun ? { text: 'min', value: String(min), label: `Min: ${format(min)}` } : null,
    reset
      ? { text: 'default', value: reset.value, label: `Use the default: ${reset.label}` }
      : null,
    max != null
      ? noun
        ? { text: 'all', value: String(max), label: `All: ${format(max)} ${noun}` }
        : { text: 'max', value: String(max), label: `Max: ${format(max)}` }
      : null,
    ...fill,
  ].filter((x) => x !== null));
  const clears = clear && v !== '';
  if (!clears && !words.length) {
    return html`<${Input} value=${v} onInput=${onInput} bad=${bad} ...${rest} />`;
  }
  const ends = clears
    ? html`<span class="value-ends"><button type="button" class="icon-btn" aria-label="Clear"
        data-tip="Clear" onClick=${() => onInput('')}><${Icon} name="x" /></button></span>`
    : null;
  const bar = words.length
    ? html`<span class="value-bar">${
      words.map((f, i) =>
        html`
          ${i
            ? html`<span class="dot" aria-hidden="true">·</span>`
            : null}<button type="button" class="link-btn" aria-label=${f.label} data-tip=${f.label}
            disabled=${v === f.value} onClick=${() => onInput(f.value)}>${f.text}</button>
        `
      )
    }</span>`
    : null;
  return html`
    <span
      class="value-input"><span class=${'value-in' +
        (clears
          ? ' ends-1'
          : '')}><${Input} value=${v} onInput=${onInput} bad=${bad} ...${rest} />${ends}</span>${bar}</span>
  `;
}

/**
 * What a typed input does with what reaches it (S12.18): a key outside its kind's characters
 * is refused and marked; a paste, or text put in whole (autofill, dictation), is cleaned first
 * and taken whole or refused whole; any change clears the mark; the value is checked when the
 * field is left, at Enter, and at Save (a form's submit asks every typed input in it,
 * `checkOnSubmit`). `mark` is the current mark; `onMark` sets it.
 * A number that groups as it is typed (`way`, S12.18.8) is typed through `typeNatural` or
 * `typeRegister`: the field shows it grouped and its value is the text without the commas.
 * @param {{ kind: string, bounds: import('./kinds.js').Bounds,
 *   format?: (n: any) => string, mark: string | null, onMark: (m: string | null) => void,
 *   onInput: (v: string) => void, onCommit?: (v: string, ok: boolean) => void,
 *   way?: import('./numbers.js').Way | null }} p
 */
export function typedHandlers({ kind, bounds, format, mark, onMark, onInput, onCommit, way }) {
  const k = kindOf(kind);
  /** What the field holds: its text, less a number's grouping. @param {HTMLInputElement} el */
  const read = (el) => (way ? ungroup(el.value) : el.value);
  /** One key or paste, typed as the field's way takes it. @param {HTMLInputElement} el @param {import('./numbers.js').Op} op */
  const type = (el, op) => {
    if (!way) return;
    const end = el.value.length;
    const next = (way.entry === 'register' ? typeRegister : typeNatural)(
      { text: el.value, start: el.selectionStart ?? end, end: el.selectionEnd ?? end },
      op,
      way,
    );
    if (next.refused) {
      onMark(next.refused);
      el.setAttribute('data-tip', next.refused);
      showTip(el);
      return;
    }
    el.value = next.text;
    el.setSelectionRange(next.start, next.end);
    if (mark) hideTip();
    onMark(null);
    onInput(ungroup(next.text));
  };
  const refuse = (/** @type {HTMLElement} */ el) => {
    const why = says(k, bounds);
    onMark(why);
    el.setAttribute('data-tip', why);
    showTip(el);
  };
  /** Put text in at the selection, cleaned, or refuse it whole. @param {HTMLInputElement} el @param {string} text */
  const put = (el, text) => {
    const clean = cleanPaste(k, bounds, text);
    if (clean === null) return refuse(el);
    if (way) {
      // A paste is a whole value (S12.18.8.3): a register's is read as an amount, not as cents.
      if (way.entry === 'register') {
        // Text that doesn't read as an amount stays as it is, marked when the field is left.
        el.value = k.read(clean) ? clean : shownText(clean, way);
        el.setSelectionRange(el.value.length, el.value.length);
        onMark(null);
        hideTip();
        onInput(ungroup(el.value));
      } else type(el, { insert: clean });
      return;
    }
    const end = el.value.length;
    el.setRangeText(clean, el.selectionStart ?? end, el.selectionEnd ?? end, 'end');
    onMark(null);
    hideTip();
    onInput(el.value);
  };
  const commit = (/** @type {string} */ v) => {
    const m = check(k, bounds, v, format);
    onMark(m);
    onCommit?.(v, !m);
    return m;
  };
  return {
    'data-kind': kind,
    onBeforeInput: (/** @type {InputEvent} */ e) => {
      const el = /** @type {HTMLInputElement} */ (e.currentTarget);
      if (
        way && (e.inputType === 'deleteContentBackward' || e.inputType === 'deleteContentForward')
      ) {
        e.preventDefault();
        type(el, e.inputType === 'deleteContentBackward' ? { back: true } : { forward: true });
        return;
      }
      if (!k.chars || !e.data) return;
      if (e.inputType !== 'insertText' && e.inputType !== 'insertReplacementText') return;
      if (accepts(k, bounds, e.data)) {
        if (way) {
          e.preventDefault();
          // A key is typed; text put in whole (autofill, dictation) is a whole value, as a
          // paste is (S12.18.2).
          if ([...e.data].length > 1) put(el, e.data);
          else type(el, { insert: e.data });
        }
        return;
      }
      e.preventDefault();
      // One key is refused; more at once is put in as a paste is.
      if ([...e.data].length > 1) put(el, e.data);
      else refuse(el);
    },
    onPaste: (/** @type {ClipboardEvent} */ e) => {
      if (!k.chars) return;
      e.preventDefault();
      put(
        /** @type {HTMLInputElement} */ (e.currentTarget),
        e.clipboardData?.getData('text') ?? '',
      );
    },
    onDrop: (/** @type {DragEvent} */ e) => {
      if (k.chars) e.preventDefault();
    },
    onInput: (/** @type {string} */ v) => {
      if (mark) hideTip();
      onMark(null);
      // What reaches here past the keys above (a word deleted, a cut, an undo) is read again.
      onInput(way ? ungroup(v).replace(/[^\d.-]/g, '') : v);
    },
    onBlur: (/** @type {any} */ e) => {
      const el = /** @type {HTMLInputElement} */ (e.currentTarget);
      if (way && way.entry === 'natural') {
        const pad = padded(el.value, way);
        if (pad !== el.value) {
          el.value = pad;
          onInput(ungroup(pad));
        }
      }
      commit(read(el));
    },
    onKeyDown: (/** @type {KeyboardEvent} */ e) => {
      if (e.key === 'Enter') commit(read(/** @type {HTMLInputElement} */ (e.currentTarget)));
    },
    'onmk-check': (/** @type {CustomEvent} */ e) => {
      if (commit(read(/** @type {HTMLInputElement} */ (e.currentTarget)))) e.detail.marked = true;
    },
  };
}

/**
 * A field for one kind of value (S12.18): an amount, a quantity, a percent, a count, a
 * duration, a date, a time of day, a web address or text, over `<ValueInput>`'s controls.
 * `min` and `max` bound it (and give Min, Max or All; a date's bound its calendar instead);
 * `above` (a value it must be more than) and `atMost` bound it with no button; a field takes a
 * negative only where its least allows one, or `negative` says so. `mark` is a mark the screen
 * sets (a bound another field sets), shown as this field's own are: a red border and a tooltip.
 * `onCommit` hears the value when the field is left or Enter is pressed, with whether it
 * passed: a field with no Save takes it then.
 *
 * An amount or a quantity groups as it is typed (S12.18.8): `entry` says how (`register` for
 * dollars, `natural` for the rest, as its kind has it; `none` types it as text), and `places`
 * how many places it has. `prefix` and `suffix` are its unit, shown in the field (S12.18.9):
 * an amount's `$` is its kind's, `prefix={null}` leaves it out.
 * @param {{ kind?: string, value: string, onInput: (v: string) => void,
 *   onCommit?: (v: string, ok: boolean) => void, mark?: string | null, negative?: boolean,
 *   above?: number | string, atMost?: number | string, min?: number | string, max?: number | string, noun?: string, format?: (n: any) => string,
 *   clear?: boolean, reset?: { value: string, label: string }, fill?: Fill[], bad?: boolean,
 *   entry?: 'natural' | 'register' | 'none', places?: number | null, prefix?: string | null,
 *   suffix?: string | null, readonly?: boolean, [k: string]: any }} p
 */
export function TypedInput(
  {
    kind = 'text',
    value,
    onInput,
    onCommit,
    mark: outer,
    negative,
    above,
    atMost,
    bad,
    readonly,
    entry,
    places,
    prefix,
    suffix,
    ...rest
  },
) {
  const [mark, setMark] = useState(/** @type {string | null} */ (null));
  const k = kindOf(kind);
  if (useReading(readonly)) {
    // Read, the value as its kind shows it; a web address is a link. Its controls go: they
    // fill in what is typed.
    const { id, style, 'aria-label': label, 'aria-describedby': described } = rest;
    const text = readText(kind, value, rest.format);
    return html`
      <${ReadValue} text=${text} id=${id} style=${style} aria-label=${label}
        aria-describedby=${described} data-help=${rest['data-help']}
        href=${kind === 'url' && !k.read(String(value ?? '').trim()) ? value : null}
        external=${kind === 'url'} />
    `;
  }
  const least = above ?? rest.min;
  const bounds = {
    negative: negative ?? (least == null || Number(least) < 0),
    min: rest.min,
    max: rest.max,
    above,
    atMost,
  };
  const shown = mark || outer || null;
  const how = entry ?? k.entry;
  /** @type {import('./numbers.js').Way | null} */
  const way = how && how !== 'none' && k.numeric
    ? {
      entry: how,
      places: places !== undefined ? places : k.places ?? null,
      negative: !!bounds.negative,
    }
    : null;
  const handlers = typedHandlers({
    kind,
    bounds,
    format: rest.format,
    mark,
    onMark: setMark,
    onInput,
    onCommit,
    way,
  });
  // The mark is the field's tooltip, and its description for a screen reader.
  const marked = {
    bad: bad || !!shown,
    'data-tip': shown || undefined,
    'aria-description': shown || undefined,
    'aria-invalid': shown || bad || rest['aria-invalid'] ? 'true' : undefined,
  };
  if (kind === 'date' || kind === 'time') {
    // Typed as people write them (S12.18.10, S12.18.11); a date's bounds bound its calendar.
    const { min, max, clear: _c, reset: _r, fill: _f, noun: _n, format: _fm, type: _t, ...pass } =
      rest;
    const C = kind === 'date' ? DateInput : TimeInput;
    return html`
      <${C} value=${value} min=${min} max=${max} ...${pass} ...${handlers}
        onBeforeInput=${undefined} onPaste=${undefined} onDrop=${undefined} ...${marked} />
    `;
  }
  if (way) {
    const unit = prefix === undefined ? k.prefix : prefix;
    return html`
      <${ValueInput} value=${shownText(value ?? '', way)} inputmode=${k.inputmode} num=${true}
        prefix=${unit || undefined} suffix=${suffix || undefined} ...${rest} ...${handlers}
        ...${marked} />
    `;
  }
  return html`
    <${ValueInput} value=${value} inputmode=${k.inputmode} prefix=${prefix || undefined}
      suffix=${suffix || undefined} num=${!!suffix || !!prefix} ...${rest} ...${handlers}
      ...${marked} />
  `;
}

/**
 * A number held as its caller asks (S17.3.10.2): `valueType` `dec` (an exact decimal's text, the
 * default), `number` (a JS number in whole units: refused past 15 significant digits) or
 * `minor` (a BigInt of the smallest unit, `minorDigits` places below a whole one). `show` is
 * how many places what is shown and typed sits from what is held: bitcoin held in BTC and
 * shown in sats is 8; held in sats and shown in BTC, with `minor` and 8 `minorDigits`, 0.
 * `onChange` hears what is held, or null for a blank; text that can't be held yet is kept and
 * marked. The rest is `<TypedInput>`'s (a `quantity` by default).
 * @param {{ value: any, onChange: (v: any) => void, valueType?: 'dec' | 'number' | 'minor',
 *   minorDigits?: number, show?: number, kind?: string, [k: string]: any }} p
 */
export function NumberInput(
  { value, onChange, valueType, minorDigits, show, kind = 'quantity', ...rest },
) {
  const held = { valueType, minorDigits, show };
  const [text, setText] = useState(() => textOf(value, held));
  const [mark, setMark] = useState(/** @type {string | null} */ (null));
  // What this field last said it holds: a value the caller sets otherwise is shown afresh.
  const sent = useRef(/** @type {any} */ (value));
  if (String(value ?? '') !== String(sent.current ?? '')) {
    sent.current = value;
    const t = textOf(value, held);
    if (t !== text) setText(t);
  }
  const why = valueType === 'number'
    ? 'At most 15 digits.'
    : `At most ${(minorDigits ?? 0) - (show ?? 0)} places.`;
  return html`
    <${TypedInput} kind=${kind} value=${text} mark=${mark || rest.mark} onInput=${(
      /** @type {string} */ t,
    ) => {
      setText(t);
      const v = valueOf(t, held);
      if (v === undefined && /^-?\d+(\.\d*)?$/.test(t)) {
        setMark(why);
        return;
      }
      setMark(null);
      if (v === undefined) return;
      sent.current = v;
      onChange(v);
    }}
      ...${rest} />
  `;
}

/**
 * At a form's submit, every typed input in it checks what it holds and marks what fails
 * (S12.18.3). The save goes on: the draft refuses what doesn't read, at its field, and the
 * server whatever else. Installed once, on the document, ahead of every form's own submit.
 */
export function checkOnSubmit() {
  document.addEventListener('submit', (e) => {
    const form = /** @type {HTMLFormElement} */ (e.target);
    for (const el of form.querySelectorAll('[data-kind]')) {
      el.dispatchEvent(new CustomEvent('mk-check', { detail: { marked: false } }));
    }
  }, true);
}

/**
 * A count from 1 to `max`, empty until one is typed, with **All** right after it (R3.11).
 * @param {{ value: string, onInput: (v: string) => void, max: number, noun: string,
 *   id?: string }} p
 */
export function CountInput({ value, onInput, max, noun, ...rest }) {
  return html`
    <${TypedInput} kind="count" value=${value} onInput=${onInput} min=${1} max=${max}
      noun=${noun} ...${rest} />
  `;
}

/**
 * A list. Read, the chosen option's words in the list's place; one naming a record with a page
 * of its own (an account, a budget) is a link to it, when it is among the options, so one the
 * reader may open.
 * @param {{ value: any, onChange: (v: string) => void, options: ([string, string] | string)[],
 *   id?: string, readonly?: boolean, [k: string]: any }} p
 */
export function Select({ value, onChange, options, readonly, ...rest }) {
  if (useReading(readonly)) {
    const v = String(value ?? '');
    const chosen = options.map((o) => (Array.isArray(o) ? o : [o, o])).find(([x]) => x === v);
    // A blank reads as blank, whatever its option says ("None", "Choose…").
    const text = v === '' ? '—' : chosen ? chosen[1] || '—' : 'Not shared with you';
    return html`
      <${ReadValue} text=${text} select href=${chosen ? pageOf(v) : null} id=${rest.id}
        style=${rest.style} aria-label=${rest['aria-label']}
        aria-describedby=${rest['aria-describedby']} data-help=${rest['data-help']} />
    `;
  }
  return html`
    <select class="in" value=${value ?? ''}
      onChange=${(/** @type {any} */ e) => onChange(e.currentTarget.value)} ...${rest}>
        ${options.map((o) => {
          const [v, l] = Array.isArray(o) ? o : [o, o];
          return html`<option value=${v}>${l}</option>`;
        })}
      </select>
  `;
}

/**
 * A switch: a button with role=switch. `why` shows it off, saying why (S12.19.1): it stays in
 * reach of the keyboard and its tooltip gives the reason.
 * One switch per row of a table names its heading with help, keeping a unique id.
 * Read, its footprint holds a check or a dash, never a live switch (S12.18.6).
 * @param {{ on: boolean, onChange: (v: boolean) => void, label: string, id?: string,
 *   disabled?: boolean, help?: string, why?: string | null, readonly?: boolean }} p
 */
export function Switch({ on, onChange, label, id, disabled, help, why, readonly }) {
  const ids = useContext(IdPrefix);
  if (useReading(readonly)) {
    return html`
      <span class=${'switch read' + (on ? ' on' : '')} role="switch" aria-readonly="true"
        aria-checked=${on ? 'true' : 'false'} aria-label=${label} tabindex="0"
        id=${ids + (help ? 'x-' : 'f-') + (id || slug(label))} data-help=${help}><${Icon}
        name=${on ? 'check' : 'minus'} /></span>
    `;
  }
  return html`
    <button type="button" class=${'switch' + (on ? ' on' : '')} role="switch"
      aria-checked=${on ? 'true' : 'false'} aria-label=${label} id=${ids + (help ? 'x-' : 'f-') +
        (id || slug(label))} data-help=${help}
      disabled=${disabled}
      aria-disabled=${why ? 'true' : undefined} data-tip=${why || undefined}
      aria-description=${why || undefined} onClick=${() => why || onChange(!on)}></button>
  `;
}

/**
 * A row with a label and a switch, as Settings and account forms use.
 * @param {{ label: string, hint?: string, on: boolean, onChange: (v: boolean) => void,
 *   disabled?: boolean, readonly?: boolean }} p
 */
export function SwitchRow({ label, hint, on, onChange, disabled, readonly }) {
  return html`
    <div
      class="list-item"><span class="grow">${label}${hint
        ? html`<div class="small dim">${hint}</div>`
        : null}</span><${Switch} on=${on} onChange=${onChange} label=${label} disabled=${disabled}
          readonly=${readonly} /></div>
  `;
}

/**
 * A segmented choice, such as None · Read · Write.
 * Read, the chosen one's words.
 * @param {{ value: string, onChange: (v: string) => void, options: [string, string][],
 *   label: string, disabled?: string[], readonly?: boolean }} p
 */
export function Seg({ value, onChange, options, label, disabled = [], readonly }) {
  if (useReading(readonly)) {
    const chosen = options.find(([v]) => v === value);
    return html`<${ReadValue} text=${chosen ? chosen[1] : '—'} aria-label=${label} />`;
  }
  return html`<div class="seg" role="radiogroup" aria-label=${label}>${
    options.map(([v, l]) =>
      html`
        <button type="button" role="radio" aria-checked=${value === v ? 'true' : 'false'}
          class=${value === v ? 'on' : ''} disabled=${disabled.includes(v)}
          onClick=${() => onChange(v)}>${l}</button>
      `
    )
  }</div>`;
}

/**
 * The server's refusal of the form as a whole, or of fields this form doesn't show.
 * @param {{ error: any, shown?: string[] }} p
 */
export function FormError({ error, shown = [] }) {
  if (!error) return null;
  const errs = (error.errors || []).filter((/** @type {any} */ e) => !shown.includes(e.field));
  const text = errs.length
    ? errs.map((/** @type {any} */ e) => e.message).join(' ')
    : error.message;
  if (error.errors?.length && !errs.length) return null;
  return html`<div class="notice bad" role="alert">${text}${
    error.errorId ? html`${' '}<span class="small dim">(${error.errorId})</span>` : null
  }</div>`;
}

/**
 * The message for a field from an ApiError, if any.
 * @param {any} error
 * @param {string} field
 */
export function errAt(error, field) {
  return error?.errors?.find((/** @type {any} */ e) => e.field === field)?.message ?? null;
}
