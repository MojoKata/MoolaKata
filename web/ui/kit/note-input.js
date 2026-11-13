// A note's field (requirements S12.18.15): the editor while it is being written, loaded the
// first time one is edited; read, the note drawn by NoteView, with no editor loaded. It holds
// the note as its document, or null when it holds no text; past its limits it is marked when
// left and at Save, as any field is (R3.11).
import { useEffect, useState } from 'preact/hooks';
import { html } from './html.js';
import { useReading } from './fields.js';
import { checkNote } from './note-check.js';
import { noPages, NoteView } from './note-view.js';

/** The editor's module, once loaded. @type {any} */
let loaded = null;

/** Loads the editor, once for the page. */
export function loadEditor() {
  return import('./note-editor.js').then((m) => (loaded = m));
}

/**
 * @param {{ value: any, onChange: (doc: any) => void, id?: string, placeholder?: string,
 *   readonly?: boolean, disabled?: boolean, own?: import('./note-links.js').Own[],
 *   pages?: import('./note-view.js').Pages, open?: (page: string) => void, empty?: any }} p
 */
export function NoteInput(
  { value, onChange, id, placeholder, readonly, disabled, own, pages = noPages, open, empty },
) {
  const reading = useReading(readonly);
  const [mod, setMod] = useState(loaded);
  const [bad, setBad] = useState(/** @type {string | undefined} */ (undefined));
  useEffect(() => {
    if (!reading && !mod) loadEditor().then(setMod);
  }, [reading]);
  const check = () => setBad(value ? checkNote(value).problems[0] : undefined);
  if (reading) {
    return html`
      <${NoteView} doc=${value} pages=${pages} open=${open} id=${id}
        empty=${empty ?? html`<span class="dim">No note</span>`} />
    `;
  }
  if (!mod) {
    return html`
      <div class="note loading" aria-busy="true">
        <div class="note-bar"></div>
        <div class="note-body"><span class="dim small">Loading the editor…</span></div>
      </div>
    `;
  }
  return html`
    <${mod.NoteEditor} value=${value} id=${id} placeholder=${placeholder}
      disabled=${disabled} own=${own} pages=${pages} open=${open} bad=${bad}
      onLeave=${check} onChange=${(/** @type {any} */ doc) => {
        setBad(undefined);
        onChange(doc);
      }} />
  `;
}
