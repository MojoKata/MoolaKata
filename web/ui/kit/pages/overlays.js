// The ui-kit's page for what opens over the page: a dialog (and one over it), the question
// before a delete, a menu, a toast, a tooltip; and the pager.
import { signal } from '@preact/signals';
import { useState } from 'preact/hooks';
import { html } from '../html.js';
import { Dialog, openDialog } from '../dialog.js';
import { confirmAction } from '../confirm.js';
import { openMenu } from '../menu.js';
import { toast } from '../toast.js';
import { Field, Input } from '../fields.js';
import { Pager } from '../pager.js';
import { Demo, Page, show } from './parts.js';

const size = signal(100);

/**
 * A dialog with a field; changes ask before they are lost. Each opened over another is
 * narrower and taller than the one beneath it, and can open one more over itself.
 * @param {any} p
 */
function Edit({ close, depth = 0 }) {
  const [v, setV] = useState('');
  return html`
    <${Dialog} title=${depth ? `Over it (${depth})` : 'Edit a note'} close=${close}
      changed=${() => v !== ''} onSubmit=${() => close(v)}
      size=${{ width: `${520 - depth * 90}px`, minHeight: `${240 + depth * 90}px` }}
      footer=${html`
        <button type="button" class="btn" data-cancel>Cancel</button>
        <button type="button" class="btn" onClick=${() =>
          openDialog(Edit, { depth: depth + 1 })}>Open one over it</button>
        <button type="submit" class="btn primary">Save</button>
      `}>
      <${Field} label="Note" id="note">
        <${Input} value=${v} onInput=${setV} />
        </${Field}>
        </${Dialog}>
  `;
}

export default function OverlaysPage() {
  const [line, setLine] = useState('nothing yet');
  const [page, setPage] = useState(1);
  const said = (/** @type {any} */ x) => setLine(show(x));
  return html`
    <${Page} title="Dialogs, menus and the rest" about=${html`A dialog traps the focus and gives
      it back when it closes; one opened from another opens over it, the one beneath waiting.
      A dialog holding changes asks before Escape, ✕ or Cancel lose them. The question before
      a delete has No focused. A menu opens under its button and gives the focus back. A toast
      says what happened; a tooltip shows on the pointer and on the focus.`}
      keys=${[
        [
          'Escape',
          'Closes the dialog on top, or asks first while it holds changes; closes a menu.',
        ],
        ['Tab', 'Goes round the dialog on top (and what the page keeps beside it).'],
        ['Enter', 'In the question: No, the default.'],
      ]}
      props=${[
        [
          'openDialog(component, props)',
          'Promise',
          'Opens a dialog; resolves with what it closes with.',
        ],
        [
          'Dialog: title, close, footer, changed, save',
          '',
          'changed: whether it holds changes; save: saves from the question.',
        ],
        [
          'confirmAction({ title, detail, yes })',
          'Promise<boolean>',
          'The question; true only for Yes.',
        ],
        ['openMenu(event, items)', '', 'A menu under the button the event came from.'],
        ['toast(text)', '', 'A line that goes by itself.'],
        [
          'placeDialogs({ beside, width, masked, changes })',
          '',
          'What the app keeps beside dialogs, masks under them, and holds changes in.',
        ],
        [
          'Pager: shown, page, total, onPage, size, newer',
          '',
          'size: the page size, in a signal the pager changes.',
        ],
      ]}>
      <${Demo} id="dialog" title="A dialog" report=${line}>
        <button type="button" class="btn" onClick=${async () =>
          said(await openDialog(Edit, {}))}>Open a dialog</button>
        </${Demo}>
        <${Demo} id="confirm" title="The question before a delete" report=${line}>
          <button type="button" class="btn danger" onClick=${async () =>
            said(
              await confirmAction({
                title: 'Delete this rule?',
                detail: 'Transactions it filed keep their category.',
              }),
            )}>Delete…</button>
          </${Demo}>
          <${Demo} id="menu" title="A menu" report=${line}>
            <button type="button" class="btn" onClick=${(/** @type {MouseEvent} */ e) =>
              openMenu(e, [
                { label: 'Rename', onSelect: () => said('Rename') },
                { label: 'Export CSV', onSelect: () => said('Export CSV') },
                { label: 'Delete', onSelect: () => said('Delete') },
              ])}>More ▾</button>
            </${Demo}>
            <${Demo} id="toast" title="A toast and a tooltip">
              <div class="toolbar">
                <button type="button" class="btn" onClick=${() => toast('Saved')}>Save</button>
                <span class="pill" tabindex="0"
                  data-tip="Every row matches the statement.">reconciled</span>
              </div>
              </${Demo}>
              <${Demo} id="pager" title="The pager" report=${String(page)}>
                <${Pager} label="kit" shown=${size.value} page=${page} total=${2340}
                  onPage=${setPage}
                  size=${size} newer=${3} onNewer=${() => setPage(1)} />
                </${Demo}>
                </${Page}>
  `;
}
