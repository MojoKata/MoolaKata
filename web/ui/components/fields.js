// Form fields: a label, the control, a hint and the server's refusal at that field (R3.7).
// Each control's id is "f-" and its label's slug, which the help pane follows (S12.7.3).
import { cloneElement, createContext, isValidElement } from 'preact';
import { useContext, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { slug } from '../app/format.js';
import { READ_ONLY } from '../app/draft.js';
import { Icon } from './icon.js';
import { accepts, check, cleanPaste, kindOf, pageOf, readText, says } from '../app/kinds.js';
import { hideTip, showTip } from './tooltip.js';

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
 * Why a form's own actions (add a part, remove a row) are off while it reads, or null: the
 * form's reason, *Shared with you to read* unless it gave another (S12.19.1).
 */
export function useReadWhy() {
  const form = useContext(Reading);
  return typeof form === 'string' ? form : form ? READ_ONLY : null;
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
    'aria-labelledby': rest['aria-label'] || !id ? undefined : id + '-label',
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
    <label for=${fid} id=${fid + '-label'}>${label}</label>
    ${control}
    ${hint ? html`<div class="hint">${hint}</div>` : null}
    ${error ? html`<div class="err" id=${fid + '-err'} role="alert">${error}</div>` : null}
  </div>`;
}

/**
 * A text input bound to a value. A password input carries an eye button that shows what was
 * typed and hides it again (S12.1.3).
 * @param {{ value: any, onInput: (v: string) => void, type?: string, placeholder?: string,
 *   bad?: boolean, autocomplete?: string, id?: string, inputmode?: string, required?: boolean,
 *   readonly?: boolean }} p
 */
export function Input({ value, onInput, type = 'text', placeholder, bad, readonly, ...rest }) {
  const [shown, setShown] = useState(false);
  if (useReading(readonly)) {
    const v = String(value ?? '');
    return html`
      <${ReadValue} text=${v === '' ? '—' : type === 'password' ? '••••••••' : v}
        ...${rest} />
    `;
  }
  const input = html`
    <input class=${'in' + (bad ? ' bad' : '')} type=${type === 'password' && shown
      ? 'text'
      : type} value=${value ?? ''}
      placeholder=${placeholder} onInput=${(/** @type {any} */ e) => onInput(e.currentTarget.value)}
      ...${rest} />
  `;
  if (type !== 'password') return input;
  return html`<span class="pw">${input}<button type="button" class="icon-btn"
    aria-label=${shown ? 'Hide password' : 'Show password'} aria-pressed=${shown ? 'true' : 'false'}
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
 * (R3.11). Inside it, at its end: × clears it (`clear`), ↺ puts back its default (`reset`).
 * Right after it, a little apart: from `max`, **All** for a count (`noun` given: "All: 2
 * contracts") or **Max** for an amount, and from `min` **Min** (an amount only: a count's least
 * is quicker typed); then any other value in `fill`. Each names its value as its tooltip
 * (`format` shows it as the field does); one inside hides, and one outside greys out, while the
 * field holds its value. It draws the controls only: `<TypedInput>` checks what is typed.
 * @param {{ value: string, onInput: (v: string) => void, clear?: boolean,
 *   reset?: { value: string, label: string }, min?: number | string, max?: number | string,
 *   noun?: string, format?: (n: any) => string, fill?: Fill[], id?: string,
 *   inputmode?: string, type?: string, placeholder?: string, bad?: boolean, [k: string]: any }} p
 */
export function ValueInput(
  { value, onInput, clear, reset, min, max, noun, format = String, fill = [], bad, ...rest },
) {
  const v = value ?? '';
  const bounds = [
    min != null && !noun ? { text: 'Min', value: String(min), label: `Min: ${format(min)}` } : null,
    max != null
      ? noun
        ? { text: 'All', value: String(max), label: `All: ${format(max)} ${noun}` }
        : { text: 'Max', value: String(max), label: `Max: ${format(max)}` }
      : null,
  ].filter((x) => x !== null);
  const control = (
    /** @type {string} */ name,
    /** @type {string} */ tip,
    /** @type {string} */ to,
  ) =>
    html`
      <button type="button" class="icon-btn" aria-label=${tip} data-tip=${tip}
        onClick=${() => onInput(to)}><${Icon} name=${name} /></button>
    `;
  const inside = [
    clear && v !== '' ? control('x', 'Clear', '') : null,
    reset && v !== reset.value
      ? control('reset', `Use the default: ${reset.label}`, reset.value)
      : null,
  ].filter(Boolean);
  const outside = [...bounds, ...fill];
  if (!inside.length && !outside.length) {
    return html`<${Input} value=${v} onInput=${onInput} bad=${bad} ...${rest} />`;
  }
  return html`
    <span
      class="value-input"><span class=${'value-in' +
        (inside.length
          ? ` ends-${inside.length}`
          : '')}><${Input} value=${v} onInput=${onInput} bad=${bad} ...${rest} />${inside.length
        ? html`<span class="value-ends">${inside}</span>`
        : null}</span>${outside.map((f) =>
          html`
            <button type="button" class="btn" aria-label=${f.label} data-tip=${f.label}
              disabled=${v === f.value} onClick=${() => onInput(f.value)}>${f.text}</button>
          `
        )}</span>
  `;
}

/**
 * What a typed input does with what reaches it (S12.18): a key outside its kind's characters
 * is refused and marked; a paste, or text put in whole (autofill, dictation), is cleaned first
 * and taken whole or refused whole; any change clears the mark; the value is checked when the
 * field is left, at Enter, and at Save (a form's submit asks every typed input in it,
 * `checkOnSubmit`). `mark` is the current mark; `onMark` sets it.
 * @param {{ kind: string, bounds: import('../app/kinds.js').Bounds,
 *   format?: (n: any) => string, mark: string | null, onMark: (m: string | null) => void,
 *   onInput: (v: string) => void, onCommit?: (v: string, ok: boolean) => void }} p
 */
export function typedHandlers({ kind, bounds, format, mark, onMark, onInput, onCommit }) {
  const k = kindOf(kind);
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
      if (!k.chars || !e.data) return;
      if (e.inputType !== 'insertText' && e.inputType !== 'insertReplacementText') return;
      if (accepts(k, bounds, e.data)) return;
      e.preventDefault();
      const el = /** @type {HTMLInputElement} */ (e.currentTarget);
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
      onInput(v);
    },
    onBlur: (/** @type {any} */ e) => void commit(e.currentTarget.value),
    onKeyDown: (/** @type {KeyboardEvent} */ e) => {
      if (e.key === 'Enter') commit(/** @type {HTMLInputElement} */ (e.currentTarget).value);
    },
    'onmk-check': (/** @type {CustomEvent} */ e) => {
      if (commit(/** @type {HTMLInputElement} */ (e.currentTarget).value)) e.detail.marked = true;
    },
  };
}

/**
 * A field for one kind of value (S12.18): an amount, a quantity, a percent, a count, a
 * duration, a date, a web address or text, over `<ValueInput>`'s controls. `min` and `max`
 * bound it (and give Min, Max or All); `above` (a value it must be more than) and `atMost`
 * bound it with no button; a field takes a negative only where its least allows one, or
 * `negative` says so. `mark` is a mark the screen sets (a bound another field sets), shown as
 * this field's own are: a red border and a tooltip. `onCommit` hears the value when
 * the field is left or Enter is pressed, with whether it passed: a field with no Save takes
 * it then.
 * @param {{ kind?: string, value: string, onInput: (v: string) => void,
 *   onCommit?: (v: string, ok: boolean) => void, mark?: string | null, negative?: boolean,
 *   above?: number | string, atMost?: number | string, min?: number | string, max?: number | string, noun?: string, format?: (n: any) => string,
 *   clear?: boolean, reset?: { value: string, label: string }, fill?: Fill[], bad?: boolean,
 *   readonly?: boolean, [k: string]: any }} p
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
  const handlers = typedHandlers({
    kind,
    bounds,
    format: rest.format,
    mark,
    onMark: setMark,
    onInput,
    onCommit,
  });
  // The mark is the field's tooltip, and its description for a screen reader.
  const marked = {
    bad: bad || !!shown,
    'data-tip': shown || undefined,
    'aria-description': shown || undefined,
    'aria-invalid': shown || bad || rest['aria-invalid'] ? 'true' : undefined,
  };
  if (kind === 'date') {
    // A date is taken as it is chosen: the picker's change, as a list's choice is.
    return html`
      <${ValueInput} value=${value} type="date" ...${rest} ...${handlers}
        onBeforeInput=${undefined} onPaste=${undefined} onDrop=${undefined}
        onChange=${handlers.onBlur} ...${marked} />
    `;
  }
  return html`
    <${ValueInput} value=${value} inputmode=${k.inputmode} ...${rest} ...${handlers}
      ...${marked} />
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
    const text = chosen ? chosen[1] || '—' : v === '' ? '—' : 'Not shared with you';
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
