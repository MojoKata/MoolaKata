// The note's page (requirements S12.18.15): the editor written in, empty, off and past its
// limit; the same note read, with a link to a page this window can show and one it can't; and
// the document each keeps.
import { useState } from 'preact/hooks';
import { html } from '../html.js';
import { Field } from '../fields.js';
import { NoteInput } from '../note-input.js';
import { NoteView } from '../note-view.js';
import { checkNote, plainText } from '../note-check.js';
import { Demo, Page } from './parts.js';

/** This page's server, as a MoolaKata a pasted address of it is taken from. */
const OWN = [{ origin: 'https://moolakata.loco', base: '/ui/' }];

const NAMES = /** @type {Record<string, string>} */ ({
  'accounts/Acct_7Q2': 'Accounts › Everyday Checking',
  'budgets/Bud_3K9': 'Budgets › Groceries',
  'settings/backups': 'Settings › Backups',
});

/**
 * Pages as a linked household's window shows them: the shared screens open, Settings is out of
 * reach.
 * @param {string} page
 */
const pages = (page) => {
  const at = page.split(/[?#]/)[0];
  const tip = NAMES[at] ?? page;
  return at.startsWith('settings') ? { href: '', tip, off: true } : { href: '#notes', tip };
};

/** @param {string} text @param {any[]} [marks] */
const t = (text, marks) => (marks ? { type: 'text', text, marks } : { type: 'text', text });
/** @param {...any} c */
const p = (...c) => ({ type: 'paragraph', content: c });
/** @param {...any} c */
const li = (...c) => ({ type: 'item', content: c });

export const SAMPLE = {
  type: 'doc',
  content: [
    { type: 'heading', attrs: { level: 2 }, content: [t('Refinancing the house')] },
    p(
      t('Rates dropped to '),
      t('5.4%', [{ type: 'bold' }]),
      t(' this week. Check the '),
      t('Everyday Checking', [{ type: 'link', attrs: { page: 'accounts/Acct_7Q2' } }]),
      t(' balance before locking: '),
      t('keep three months of expenses', [{ type: 'highlight' }]),
      t('.'),
    ),
    { type: 'heading', attrs: { level: 3 }, content: [t('To do')] },
    {
      type: 'bullets',
      content: [
        li(p(t('Ask for the payoff letter'))),
        li(
          p(t('Send the paperwork')),
          { type: 'numbers', content: [li(p(t('Last two W-2s'))), li(p(t('Bank statements')))] },
        ),
        li(p(
          t('Read the '),
          t('closing cost guide', [{
            type: 'link',
            attrs: { href: 'https://www.consumerfinance.gov/owning-a-home/' },
          }]),
        )),
      ],
    },
    { type: 'quote', content: [p(t('Points pay off only if we stay past the break-even.'))] },
    {
      type: 'pre',
      content: [t('Loan      Rate   Payment\nCurrent   6.9%   $2,410\nOffer     5.4%   $2,060')],
    },
    p(
      t('Loan number '),
      t('LN-4417-22', [{ type: 'mono' }]),
      t(', '),
      t('due Friday', [{ type: 'strike' }]),
      t(' '),
      t('paid', [{ type: 'italic' }]),
      t('. '),
      t('Backups', [{ type: 'underline' }, { type: 'link', attrs: { page: 'settings/backups' } }]),
      t(' first.'),
    ),
  ],
};

const LONG = {
  type: 'doc',
  content: [p(t('All the statements, pasted. '.repeat(717) + 'One more.'))],
};

/**
 * A demo's report: the characters and bytes kept, and the document itself on request.
 * @param {{ doc: any }} p
 */
function Kept({ doc }) {
  if (!doc) return html`<span>null (no note)</span>`;
  const { chars, problems } = checkNote(doc);
  const bytes = new TextEncoder().encode(JSON.stringify(doc)).length;
  const said = `${chars.toLocaleString('en-US')} characters · ${
    bytes.toLocaleString('en-US')
  } bytes`;
  return html`
    <span>${said}</span>${problems.length
      ? html`<span> · </span><span class="deny">${problems[0]}</span>`
      : null}
    <details class="note-json small">
      <summary>The document kept</summary>
      <pre>${JSON.stringify(doc, null, 1)}</pre>
      <p class="dim">As plain text:</p>
      <pre>${plainText(doc)}</pre>
    </details>
  `;
}

/** @param {{ id: string, title: string, note?: any, first: any, label?: string,
 *   extra?: Record<string, any> }} p */
function Editing({ id, title, note, first, label = 'Note', extra = {} }) {
  const [doc, setDoc] = useState(first);
  const [opened, setOpened] = useState('');
  return html`
    <${Demo} id=${id} title=${title} note=${note}>
      <${Field} label=${label} id=${id}>
        <${NoteInput} value=${doc} onChange=${setDoc} own=${OWN} pages=${pages}
          open=${setOpened} ...${extra} />
        </${Field}>
        <div class="report small"
          data-report=${id}>Reported: <${Kept} doc=${doc} />${opened
            ? html`
              · opened <code>${opened}</code>
            `
            : null}</div>
        </${Demo}>
  `;
}

export default function NotesPage() {
  const [opened, setOpened] = useState('');
  return html`
    <${Page} title="Notes" about=${html`A note is formatted text: headings, lists, quotes,
      pre-formatted blocks, bold, italic, underline, strikethrough, highlight, monospace and
      links. It is kept as a document of those parts only, never as markup, and read without
      the editor, which loads the first time a note is edited. A link to this server
      (<code>https://moolakata.loco/ui/…</code> here) is kept as the page alone, so it opens
      on any server that shows the note.`}
      keys=${[
        ['Ctrl/Cmd+B, I, U', 'Bold, italic, underline.'],
        ['Ctrl/Cmd+Shift+X, H, M', 'Strikethrough, highlight, monospace.'],
        ['Ctrl/Cmd+Alt+0, 2, 3', 'Paragraph, heading, subheading.'],
        [
          '- or * then Space; 1. then Space',
          'A bulleted or numbered list; Backspace right after puts the text back.',
        ],
        [
          'Tab / Shift+Tab',
          'In a list: indent (three deep at most) and outdent. Elsewhere: on to the next field.',
        ],
        ['Enter / Shift+Enter', 'A new paragraph or list item; a line break inside one.'],
        ['Ctrl/Cmd+K', 'Make a link of the selection, or change the one at the caret.'],
        ['Ctrl/Cmd+Enter, Ctrl/Cmd+click', 'Open the link at the caret, or the one clicked.'],
        ['Ctrl/Cmd+Z / Shift+Z', 'Undo and redo.'],
        ['Alt+F10', 'To the toolbar; ← → along it, Escape back to the text.'],
        ['Home / End', 'The start and end of the line as drawn (Shift selecting).'],
      ]}
      props=${[
        [
          'value',
          'document | null',
          'The note as kept: its document, or null when it holds no text.',
        ],
        ['onChange', '(doc) => void', 'Each change, with the document as kept.'],
        [
          'own',
          '{ origin, base }[]',
          'Servers whose pasted addresses are kept as pages (this page’s own always is).',
        ],
        [
          'pages',
          '(page) => { href, tip, off? }',
          'Where a page opens here, its tooltip, and whether it is out of reach.',
        ],
        ['open', '(page) => void', 'Opens a page of MoolaKata in place.'],
        [
          'readonly, disabled',
          'boolean',
          'Read: the note drawn without the editor. Off: shown, not editable.',
        ],
        ['placeholder', 'string', 'What a blank note means.'],
      ]}>
      <${Editing} id="note" title="A note" first=${SAMPLE}
        note="Paste https://moolakata.loco/ui/budgets/Bud_3K9 over some words: it is kept as the page. Paste an address alone, or type one and a space: it becomes its own link." />
      <${Editing} id="note-empty" title="Empty" first=${null}
        extra=${{ placeholder: 'No note' }} />
      <${Demo} id="note-read" title="Read"
        note="As a linked household's window draws it: the Backups link names a screen it doesn't show.">
        <${NoteView} doc=${SAMPLE} pages=${pages} open=${setOpened} />
        <div class="report small" data-report="note-read">Reported: ${opened
          ? html`opened <code>${opened}</code>`
          : 'nothing yet'}</div>
        </${Demo}>
        <${Editing} id="note-off" title="Off" first=${SAMPLE} extra=${{ disabled: true }} />
        <${Editing} id="note-long" title="Past its limit" first=${LONG}
          note="The count shows from 16,000 characters; past 20,000 the note is marked when it is left, and at Save." />
        </${Page}>
  `;
}
