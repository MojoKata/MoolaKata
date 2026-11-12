// Form fields: a label, the control, a hint and the server's refusal at that field (R3.7).
// Each control's id is "f-" and its label's slug, which the help pane follows (S12.7.3).
import { cloneElement, createContext, isValidElement } from 'preact';
import { useContext, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { slug } from '../app/format.js';
import { Icon } from './icon.js';
import { outside } from '../app/bounds.js';

/** What a dialog opened over another puts before its fields' ids ("d1-"), so they stay its own
 * (S12.15.7); the help pane reads past it. */
export const IdPrefix = createContext('');

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
    <label for=${fid}>${label}</label>
    ${control}
    ${hint ? html`<div class="hint">${hint}</div>` : null}
    ${error ? html`<div class="err" id=${fid + '-err'} role="alert">${error}</div>` : null}
  </div>`;
}

/**
 * A text input bound to a value. A password input carries an eye button that shows what was
 * typed and hides it again (S12.1.3).
 * @param {{ value: any, onInput: (v: string) => void, type?: string, placeholder?: string,
 *   bad?: boolean, autocomplete?: string, id?: string, inputmode?: string, required?: boolean }} p
 */
export function Input({ value, onInput, type = 'text', placeholder, bad, ...rest }) {
  const [shown, setShown] = useState(false);
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
 * field holds its value. A value past `min` or `max`, not a number, or not whole for a count,
 * marks the field as it is typed; the server still refuses it when saved.
 * @param {{ value: string, onInput: (v: string) => void, clear?: boolean,
 *   reset?: { value: string, label: string }, min?: number, max?: number, noun?: string,
 *   format?: (n: number) => string, fill?: Fill[], id?: string, inputmode?: string,
 *   type?: string, placeholder?: string, bad?: boolean }} p
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
  const off = outside(v, min, max, noun !== undefined);
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
  return html`<span class="value-input"><span class=${
    'value-in' +
    (inside.length ? ` ends-${inside.length}` : '')
  }><${Input} value=${v} onInput=${onInput}
    bad=${bad || off} inputmode=${
    min != null || max != null ? noun ? 'numeric' : 'decimal' : undefined
  } ...${rest} />${inside.length ? html`<span class="value-ends">${inside}</span>` : null}</span>${
    [...bounds, ...fill].map((f) =>
      html`
        <button type="button" class="btn" aria-label=${f.label} data-tip=${f.label}
          disabled=${v === f.value} onClick=${() => onInput(f.value)}>${f.text}</button>
      `
    )
  }</span>`;
}

/**
 * A count from 1 to `max`, empty until one is typed, with **All** right after it (R3.11).
 * @param {{ value: string, onInput: (v: string) => void, max: number, noun: string,
 *   id?: string }} p
 */
export function CountInput({ value, onInput, max, noun, ...rest }) {
  return html`
    <${ValueInput} value=${value} onInput=${onInput} min=${1} max=${max}
      noun=${noun} ...${rest} />
  `;
}

/**
 * @param {{ value: any, onChange: (v: string) => void, options: ([string, string] | string)[],
 *   id?: string }} p
 */
export function Select({ value, onChange, options, ...rest }) {
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
 * A switch: a button with role=switch.
 * One switch per row of a table names its heading with help, keeping a unique id.
 * @param {{ on: boolean, onChange: (v: boolean) => void, label: string, id?: string,
 *   disabled?: boolean, help?: string }} p
 */
export function Switch({ on, onChange, label, id, disabled, help }) {
  const ids = useContext(IdPrefix);
  return html`
    <button type="button" class=${'switch' + (on ? ' on' : '')} role="switch"
      aria-checked=${on ? 'true' : 'false'} aria-label=${label} id=${ids + (help ? 'x-' : 'f-') +
        (id || slug(label))} data-help=${help}
      disabled=${disabled} onClick=${() => onChange(!on)}></button>
  `;
}

/**
 * A row with a label and a switch, as Settings and account forms use.
 * @param {{ label: string, hint?: string, on: boolean, onChange: (v: boolean) => void,
 *   disabled?: boolean }} p
 */
export function SwitchRow({ label, hint, on, onChange, disabled }) {
  return html`
    <div
      class="list-item"><span class="grow">${label}${hint
        ? html`<div class="small dim">${hint}</div>`
        : null}</span><${Switch} on=${on} onChange=${onChange} label=${label} disabled=${disabled} /></div>
  `;
}

/**
 * A segmented choice, such as None · Read · Write.
 * @param {{ value: string, onChange: (v: string) => void, options: [string, string][],
 *   label: string, disabled?: string[] }} p
 */
export function Seg({ value, onChange, options, label, disabled = [] }) {
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
