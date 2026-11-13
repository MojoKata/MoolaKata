// The ui-kit's page for its other fields: text, a password, a list, a switch, a segmented
// choice, a count, and a value with its fill-in controls; each also read.
import { useState } from 'preact/hooks';
import { html } from '../html.js';
import {
  CountInput,
  Field,
  Input,
  ReadValue,
  Seg,
  Select,
  SpinInput,
  Switch,
  SwitchRow,
  TypedInput,
  ValueInput,
} from '../fields.js';
import { Demo, Page, show } from './parts.js';

const KINDS = /** @type {[string, string][]} */ ([
  ['', 'Choose a kind'],
  ['checking', 'Checking'],
  ['savings', 'Savings'],
  ['brokerage', 'Brokerage'],
  ['ira', 'Roth IRA'],
]);

/** A control's demo, its value kept here and reported. @param {any} p */
function Kept({ id, title, note, first, children }) {
  const [v, setV] = useState(first);
  const [line, setLine] = useState('nothing yet');
  const set = (/** @type {any} */ x) => {
    setV(x);
    setLine(show(x));
  };
  return html`
    <${Demo} id=${id} title=${title} note=${note}
      report=${line}>${children(v, set)}</${Demo}>
  `;
}

export default function FieldsPage() {
  return html`
    <${Page} title="Fields" about=${html`A field is its label, its control, a hint and the
      refusal at it. Each control has a read persona drawn where one may only read: its value
      in the control's own box, unframed, so a form drawn read and drawn to edit don't move.
      Its <code>id</code> is on the element that takes the focus, so a guide beside the form can
      follow it.`}
      keys=${[
        ['Tab', 'Field to field; a read value is reached too, named by its label.'],
        ['Space or Enter', 'A switch: turns it over. A segmented choice: picks the button.'],
        [
          '↓ / ↑',
          'A list: its options. A small count: a step down or up (Page Down / Page Up: ten).',
        ],
        [
          'Home / End',
          'Anything typed into: the start or end of the line as drawn (Shift: selecting to it); with Ctrl or Cmd, in a box of several lines, its start or end.',
        ],
      ]}
      props=${[
        [
          'Field: label, id, hint, error',
          'string',
          'The label, the id its control takes (f- and the label’s slug), a hint under it, the refusal at it.',
        ],
        ['readonly', 'boolean', 'Every control: its read persona.'],
        ['Select: options', '[value, label][]', 'Its options; read, the chosen one’s words.'],
        ['Switch: on, onChange, label, why', '', 'why: off, saying why, still reached by Tab.'],
        [
          'SpinInput: min, max, step',
          'number',
          'A small whole number, its chevrons and ↑ ↓ stepping it within its bounds.',
        ],
        [
          'ValueInput: clear, reset, min, max, fill',
          '',
          '× in the field clears it; under it, min · default · max (all for a count) and others fill it in.',
        ],
      ]}>
      <${Kept} id="text" title="Text" first="">${(v, set) =>
        html`
          <${Field} label="Payee" id="text" hint="As you want it shown.">
            <${Input} value=${v} onInput=${set} placeholder="ex: Blue Bottle" />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="password" title="A password" first="">${(v, set) =>
        html`
          <${Field} label="Password" id="password">
            <${Input} type="password" value=${v} onInput=${set} />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="secret" title="A secret, blurred" first="">${(v, set) =>
        html`
          <${Field} label="API key" id="secret" hint="Not your sign-in: no password manager fills it.">
            <${Input} type="secret" value=${v} onInput=${set} placeholder="paste the key" />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="password-clear" title="A password with ×" first="hunter22">${(v, set) =>
        html`
          <${Field} label="Password" id="password-clear">
            <${ValueInput} type="password" value=${v} onInput=${set} clear=${true} />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="secret-clear" title="A secret with ×" first="sk-live-42">${(v, set) =>
        html`
          <${Field} label="API key" id="secret-clear">
            <${ValueInput} type="secret" value=${v} onInput=${set} clear=${true} />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="select-clear" title="A list with ×" first="savings">${(v, set) =>
        html`
          <${Field} label="Kind" id="select-clear">
            <${Select} value=${v} onChange=${set} options=${KINDS} clear=${true} />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="spin-clear" title="A small count with ×" first="6">${(v, set) =>
        html`
          <${Field} label="Months" id="spin-clear">
            <${SpinInput} value=${v} onInput=${set} min=${1} max=${12}
              clear=${true} />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="spin-unit-clear" title="A small count with a unit and ×" first="30">${(v, set) =>
        html`
          <${Field} label="Keep for" id="spin-unit-clear">
            <${SpinInput} value=${v} onInput=${set} min=${1} max=${90}
              clear=${true}
              suffix="days" />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="home-end" title="Home and End in typed text"
        note="Home and End go to the start and end of the line as drawn, Shift selecting; Ctrl or Cmd with them, in the box of several lines, to its start and end. A Mac too, where a browser would scroll the page."
        first="Rent, the car's insurance and the last of the school fees, paid from savings this month while the bonus clears; next month the account is topped back up.">${(
          v,
          set,
        ) =>
          html`
            <${Field} label="Payee" id="home-end-line">
              <input class="in" value="Whole Foods Market, South Lamar, Austin" />
              </${Field}>
              <${Field} label="Memo" id="home-end">
                <textarea class="in" rows="4" style="height:auto" value=${v}
                  onInput=${(/** @type {any} */ e) => set(e.currentTarget.value)}></textarea>
                </${Field}>
          `}</${Kept}>
      <${Kept} id="select" title="A list" first="">${(v, set) =>
        html`
          <${Field} label="Kind" id="select">
            <${Select} value=${v} onChange=${set} options=${KINDS} />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="select-read" title="A list, read" first="ira">${(v, set) =>
        html`
          <${Field} label="Kind" id="select-read">
            <${Select} value=${v} onChange=${set} options=${KINDS} readonly=${true} />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="switch" title="A switch" first=${false}>${(v, set) =>
        html`
          <${SwitchRow} label="Count in my totals" hint="Off: shown, not added in." on=${v}
            onChange=${set} />
        `}</${Kept}>
      <${Kept} id="switch-off" title="A switch, off saying why" first=${true}>${(v, set) =>
        html`<div class="list-item"><span class="grow">Reimbursable</span><${Switch} on=${v}
          onChange=${set} label="Reimbursable" why="Only its owner changes it." /></div>`}</${Kept}>
      <${Kept} id="seg" title="A segmented choice" first="read">${(v, set) =>
        html`<${Seg} label="Access" value=${v} onChange=${set} options=${[
          ['none', 'None'],
          ['read', 'Read'],
          ['write', 'Write'],
        ]} />`}</${Kept}>
      <${Kept} id="count" title="A count, with All" first="">${(v, set) =>
        html`
          <${Field} label="Contracts" id="count">
            <${CountInput} value=${v} onInput=${set} max=${5} noun="contracts" />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="spin" title="A small count, stepped" first="3">${(v, set) =>
        html`
          <${Field} label="Months" id="spin" hint="1 to 12.">
            <${SpinInput} value=${v} onInput=${set} min=${1} max=${12} />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="spin-read" title="A small count, read" first="20">${(v, set) =>
        html`
          <${Field} label="Gap limit" id="spin-read">
            <${SpinInput} value=${v} onInput=${set} min=${1} max=${100}
              readonly=${true} />
            </${Field}>
        `}</${Kept}>
      <${Kept} id="value" title="A value with Clear and Use the default" first="30">${(v, set) =>
        html`
          <${Field} label="Keep receipts for" id="value" hint="Days.">
            <${TypedInput} kind="count" value=${v} onInput=${set} clear=${true} suffix="days"
              reset=${{ value: '30', label: '30 days' }} />
            </${Field}>
        `}</${Kept}>
      <${Demo} id="read-value" title="A value read, as a link">
        <${Field} label="Account" id="read-value">
          <${ReadValue} text="Everyday checking" href="#fields" select=${true} />
        </${Field}>
      </${Demo}>
      <${Demo} id="field-error" title="A field refused">
        <${Field} label="Name" id="field-error" error="You have an account named Checking.">
          <${Input} value="Checking" onInput=${() => {}} bad=${true} />
        </${Field}>
      </${Demo}>
    </${Page}>
  `;
}
