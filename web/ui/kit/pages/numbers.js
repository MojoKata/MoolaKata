// The ui-kit's page for numbers (S12.18.8, S12.18.9): amounts from the cents, quantities as
// written, units in the field, and the ways a number is held.
import { useState } from 'preact/hooks';
import { html } from '../html.js';
import { Field, NumberInput, TypedInput } from '../fields.js';
import { Formats } from '../formats.js';
import { Demo, Page, useReport } from './parts.js';

/** A typed field and its report: the text it holds, as its caller hears it. @param {any} p */
function Typed({ id, title, note, first = '', label, ...props }) {
  const [v, set, line] = useReport(first);
  return html`
    <${Demo} id=${id} title=${title} note=${note} report=${line}>
      <${Field} label=${label || title} id=${id}>
        <${TypedInput} value=${v} onInput=${set} ...${props} />
        </${Field}>
        </${Demo}>
  `;
}

/** A number held as asked, and its report: what is held. @param {any} p */
function Held({ id, title, note, first = null, label, ...props }) {
  const [v, set, line] = useReport(first);
  return html`
    <${Demo} id=${id} title=${title} note=${note} report=${line}>
      <${Field} label=${label || title} id=${id}>
        <${NumberInput} value=${v} onChange=${set} ...${props} />
        </${Field}>
        </${Demo}>
  `;
}

export default function NumbersPage() {
  const [read] = useState('1234.5');
  return html`
    <${Page} title="Numbers" about=${html`An amount in dollars is typed from its cents, as a cash
      register takes it; a quantity is typed as written. Either way the digits sit at the right
      and the commas appear as they are typed. A unit
      (<code>$</code>, <code>shares</code>, <code>%</code>) sits in the field and is neither typed nor stored. A field holds its
      number as its caller asks: exact decimal text, a JS number, or a whole number of the
      smallest unit.`}
      keys=${[
        [
          '0–9',
          'An amount: comes in at the right of the cents (1 → 0.01, 12 → 0.12). A quantity: typed where the caret is.',
        ],
        ['.', 'An amount: passed over. A quantity: starts the fraction; a second is passed over.'],
        ['-', 'Changes the sign, where the field takes a negative.'],
        [
          'Backspace',
          'An amount: takes the last digit off. A quantity: the character before the caret; just after a comma, the digit before it.',
        ],
        ['Delete', 'A quantity: the character after the caret.'],
        [
          'Paste',
          'Read as a whole value: $1,234.5 is 1,234.50. A dollar sign, spaces and commas grouping thousands are dropped; anything else refuses it whole.',
        ],
        [
          'Tab, Enter',
          'Checked: a quantity with fixed places is padded (1,234.5 → 1,234.50), and a value that fails is marked.',
        ],
      ]}
      props=${[
        [
          'kind',
          "'money' | 'quantity' | 'percent' | 'count'",
          'What it holds; an amount groups from the cents, a quantity as written.',
        ],
        ['entry', "'register' | 'natural' | 'none'", 'How it is typed, overriding its kind.'],
        ['places', 'number | null', 'Its places: 2 for dollars; null, as many as typed.'],
        [
          'prefix',
          'string | null',
          "The unit before it: an amount's $ by default; null leaves it out.",
        ],
        ['suffix', 'string', 'The unit after it: shares, days, %, BTC.'],
        ['negative', 'boolean', 'Whether it takes a negative.'],
        ['min, max, above, atMost', 'number | string', 'Its bounds; Min, Max or All fill them in.'],
        ['valueType', "'dec' | 'number' | 'minor'", 'NumberInput: how the number is held.'],
        [
          'minorDigits',
          'number',
          'NumberInput, minor: places below a whole unit (2 for cents, 8 for sats).',
        ],
        [
          'show',
          'number',
          'NumberInput: places between what is shown and what is held (8: BTC held, sats shown).',
        ],
      ]}>
      <${Typed} id="amount" title="An amount, from the cents" kind="money" label="Amount"
        placeholder="0.00" />
      <${Typed} id="amount-filled" title="An amount, filled" kind="money" first="-1234.5"
        label="Balance" />
      <${Typed} id="amount-natural" title="An amount, typed as written" kind="money"
        entry="natural" label="Price" note="entry=natural" />
      <${Typed} id="amount-bounded" title="An amount with its bounds" kind="money"
        min="0" max="500" label="Contribution"
        note="min=0 max=500: min and max under it fill them in" />
      <${Typed} id="quantity" title="A quantity, as written" kind="quantity" suffix="shares"
        negative=${false} label="Quantity" />
      <${Typed} id="percent" title="A percent" kind="percent" suffix="%" entry="none"
        label="Rate" negative=${false} />
      <${Typed} id="refused" title="Refused" kind="money" first="12" label="Fee"
        mark="12.00 or less, the sale's fee." note="a mark the screen set" />
      <${Typed} id="off" title="Off" kind="money" first="42" label="Paid" disabled=${true} />
      <${Typed} id="read" title="Read" kind="money" first=${read} label="Paid"
        readonly=${true} />
      <${Held} id="held-dec" title="Held as exact decimal text" valueType="dec" />
      <${Held} id="held-number" title="Held as a JS number" valueType="number"
        note="past 15 significant digits it is refused" />
      <${Held} id="held-minor" title="Held in cents" kind="money" valueType="minor"
        minorDigits=${2} first=${123456n} />
      <${Held} id="btc-in-sats" title="Bitcoin held in BTC, shown in sats" show=${8}
        suffix="sats" first="0.12345678" />
      <${Formats.Provider} value=${{ bitcoinUnit: 'sats' }}>
        <${Held} id="btc-page-unit" title="Bitcoin by the page's unit (sats)" bitcoin=${true}
          first="0.00012345" note="Formats says sats here; typed and shown in sats, held in BTC." />
        <${Held} id="btc-own-unit" title="Bitcoin by its own unit (BTC)" bitcoin=${true}
          bitcoinUnit="btc" first="0.00012345" note="Its own bitcoinUnit wins over the page's." />
        </${Formats.Provider}>
        <${Held} id="sats-in-btc" title="Bitcoin held in sats, shown in BTC" valueType="minor"
          minorDigits=${8} suffix="BTC" first=${12345678n} />
        </${Page}>
  `;
}
