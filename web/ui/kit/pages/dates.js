// The ui-kit's page for dates and times of day (S12.18.10, S12.18.11).
import { html } from '../html.js';
import { Field, TypedInput } from '../fields.js';
import { Demo, Page, useReport } from './parts.js';

/** One field and its report: the text it holds. @param {any} p */
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

export default function DatesPage() {
  return html`
    <${Page} title="Dates and times" about=${html`A date reads <code>Oct 12, 2026</code> at
      rest and is typed as people write it; the calendar under it opens from its button or ↓.
      A time of day reads <code>5:30 PM</code> and is typed the same way. Each holds its value
      as text: a date <code>YYYY-MM-DD</code>, a time <code>HH:MM</code>, or what was typed
      while it isn't one yet, which is marked when the field is left.`}
      keys=${[
        [
          'Typing a date',
          '10/12/2026, 10/12/26, 10/12 (this year), oct 12, Oct 12, 2026, 12 oct, 2026-10-12, today, tomorrow, yesterday.',
        ],
        [
          'Typing a time',
          '5:30 pm, 5:30p, 530p, 5p, 17:30, noon, midnight; without am or pm, the 24-hour clock.',
        ],
        ['↓ or Alt+↓', 'In a date: opens the calendar on its date (or today).'],
        ['← → ↑ ↓', 'In the calendar: a day, a week.'],
        ['Page Up / Page Down', 'A month (with Shift, a year), the day kept or the month’s last.'],
        ['Home / End', 'The week’s first / last day.'],
        ['Enter or Space', 'Picks the day; the calendar closes and the field has the focus.'],
        ['Escape', 'Closes the calendar, the focus back in the field; a dialog around it stays.'],
        ['Tab', 'Out of the calendar closes it.'],
        [
          '↓ or the clock (a time)',
          'Opens the times by the quarter hour, on its time; 7 AM to 6 PM, the chevrons show three hours more.',
        ],
        [
          '← → ↑ ↓ (the times)',
          'A quarter, an hour; Page Up and Page Down three hours; Home and End to :00 and :45.',
        ],
      ]}
      props=${[
        ['kind', "'date' | 'time'", 'Which it is.'],
        ['value', 'string', 'YYYY-MM-DD, HH:MM, or what was typed.'],
        [
          'onInput',
          '(v: string) => void',
          'Hears the date or time as soon as what is typed reads as one, else the text.',
        ],
        [
          'min, max',
          'YYYY-MM-DD',
          'A date’s bounds: days outside are off in the calendar, and typed, refused.',
        ],
        ['readonly, disabled', 'boolean', 'Read: Oct 12, 2026. Off: no changes.'],
      ]}>
      <${Typed} id="date" title="A date" kind="date" label="Date" />
      <${Typed} id="date-east" title="Today in Kiritimati (UTC+14)" kind="date" label="Date"
        timezone="Pacific/Kiritimati"
        note="Its own timezone: today, tomorrow and yesterday are Kiritimati's." />
      <${Typed} id="date-west" title="Today in Pago Pago (UTC−11)" kind="date" label="Date"
        timezone="Pacific/Pago_Pago" note="A day behind Kiritimati, at any hour." />
      <${Typed} id="date-filled" title="A date, filled" kind="date" first="2026-10-12"
        label="Paid on" />
      <${Typed} id="date-bounded" title="A date with its bounds" kind="date"
        first="2026-10-12" min="2026-10-05" max="2026-10-25" label="As of"
        note="min=2026-10-05 max=2026-10-25" />
      <${Typed} id="date-refused" title="Refused" kind="date" first="10/45"
        label="Due date" mark="Type a date, such as 10/12/2026." />
      <${Typed} id="date-read" title="Read" kind="date" first="2026-10-12" label="Opened"
        readonly=${true} />
      <${Typed} id="time" title="A time of day" kind="time" label="Daily summary at" />
      <${Typed} id="time-filled" title="A time, filled" kind="time" first="17:30"
        label="Refresh at" />
      <${Typed} id="time-read" title="A time, read" kind="time" first="07:00"
        label="Daily summary at" readonly=${true} />
      </${Page}>
  `;
}
