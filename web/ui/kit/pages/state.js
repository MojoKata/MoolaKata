// The ui-kit's page for actions and state (S12.19), and its small building blocks.
import { useState } from 'preact/hooks';
import { html } from '../html.js';
import { Action, Attention, Empty, RowTool, StatePill } from '../state.js';
import { Avatar, Chips, Failed, Loading, Tabs } from '../bits.js';
import { Amt, Pct } from '../amount.js';
import { Icon } from '../icon.js';
import { Demo, Page, show } from './parts.js';

export default function StatePage() {
  const [line, setLine] = useState('nothing yet');
  const [chip, setChip] = useState('month');
  const [tab, setTab] = useState('state');
  const said = (/** @type {any} */ x) => setLine(show(x));
  return html`
    <${Page} title="Actions and state" about=${html`An action not open now is shown off with its
      reason, never hidden: it still takes the focus, and its reason is its tooltip and what a
      screen reader says. What the page knows is shown briefly (a line, a pill, a notice), its
      explanation a tooltip away. A record opens from a tool at its row's end: a pencil to
      edit, an eye to read.`}
      keys=${[
        ['Tab', 'Reaches an action that is off, and a pill: its tooltip says why.'],
        ['Enter or Space', 'An action: does it, unless it is off.'],
      ]}
      props=${[
        ['Action: why', 'string | null', 'Off, saying why; still reached by Tab.'],
        ['Empty: action', 'any', 'The action that makes the first one.'],
        ['StatePill: why, tone', 'string', 'Its explanation, and ok, warn, bad or info.'],
        ['Attention: actions, tone', 'any, string', 'What to do about it; warn or bad.'],
        ['RowTool: name, read, why, label', '', 'Edit name, View name, or its own label.'],
        ['Chips: value, onChange, options, label', '', 'One of a few, as a filter.'],
        ['Tabs: tabs, current, base', '', 'Tabs as links, each its own address.'],
      ]}>
      <${Demo} id="actions" title="Actions" report=${line}>
        <div class="toolbar">
          <${Action} class="btn primary" onClick=${() => said('Save')}>Save</${Action}>
          <${Action} why="Only an admin deletes a category in use." onClick=${() =>
            said('Delete')}>Delete</${Action}>
          <${RowTool} name="Whole Foods" onClick=${() => said('Edit Whole Foods')} />
          <${RowTool} name="Whole Foods" read=${true} onClick=${() => said('View Whole Foods')} />
        </div>
      </${Demo}>
      <${Demo} id="pills" title="Pills">
        <div class="toolbar">
          <${StatePill} tone="ok" why="Every row matches the statement.">reconciled</${StatePill}>
          <${StatePill} tone="warn" why="The price is from yesterday's close.">stale</${StatePill}>
          <${StatePill} tone="bad" why="The fetch has failed for two days.">failing</${StatePill}>
          <${StatePill} tone="info" why="Three new since you looked.">3 new</${StatePill}>
        </div>
      </${Demo}>
      <${Demo} id="attention" title="Something needing attention">
        <${Attention} icon=${html`<${Icon} name="info" />`} actions=${html`
          <${Action}
            class="btn sm" onClick=${() => said('Attach')}>Attach</${Action}>
        `}>
          The W-2 from Acme Corp is missing.
        </${Attention}>
      </${Demo}>
      <${Demo} id="empty" title="Nothing here yet">
        <${Empty} action=${html`<${Action} class="btn sm" onClick=${() =>
          said('Add rule')}>Add rule</${Action}>`}>
          No rules yet.
        </${Empty}>
      </${Demo}>
      <${Demo} id="chips" title="Chips" report=${chip}>
        <${Chips} label="Period" value=${chip} onChange=${setChip} options=${[
          ['month', 'Month'],
          ['quarter', 'Quarter'],
          ['year', 'Year'],
        ]} />
      </${Demo}>
      <${Demo} id="tabs" title="Tabs" report=${tab}>
        <${Tabs} current=${tab} onChange=${setTab} tabs=${[
          ['state', 'State'],
          ['fields', 'Fields'],
          ['numbers', 'Numbers'],
        ]} />
      </${Demo}>
      <${Demo} id="avatars" title="Avatars and amounts">
        <div class="toolbar">
          <${Avatar} name="Alice Griffin" id="User_alice" />
          <${Avatar} name="Bob Griffin" id="User_bob" sm=${true} />
          <${Amt} v="-1234.5" />${' '}<${Amt} v="250" signed=${true} />${' '}<${Pct} v="5.875" />
        </div>
      </${Demo}>
      <${Demo} id="loading" title="Loading, and failed">
        <${Loading} lines=${2} />
        <${Failed} error=${{ message: 'The prices could not be loaded.', errorId: 'Err_01k' }} />
      </${Demo}>
    </${Page}>
  `;
}
