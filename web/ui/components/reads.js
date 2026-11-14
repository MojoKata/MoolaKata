// A form that reads (S12.18.6): its fields drawn read, those its row shows left out, its own
// actions off saying why.
import { createContext } from 'preact';
import { useContext } from 'preact/hooks';
import { html } from '../app/html.js';
import { READ_ONLY } from '../app/draft.js';
import { Reading } from '../kit/fields.js';

/**
 * The fields a record's row already shows, by name: a dialog opened from that row and read
 * leaves them out, as it leaves out a field with nothing in it (S12.18.6.5).
 */
export const OnRow = createContext(/** @type {Set<string>} */ (new Set()));

/**
 * A form that reads (S12.18.6): every control in it reads, its own actions are off saying
 * `why`, and, read, a field with nothing in it or one its row already shows (`row`, the
 * names) is left out. `why` false: it doesn't read, and draws its children as they are.
 * @param {{ why: string | boolean | null | undefined, row?: string[], children: any }} p
 */
export function Reads({ why, row = [], children }) {
  if (!why) return children;
  return html`
    <${Reading.Provider} value=${why}>
      <${OnRow.Provider} value=${new Set(row)}>
        <div
          class="reads">${children}</div>
        </${OnRow.Provider}>
        </${Reading.Provider}>
  `;
}

/**
 * Why a form's own actions (add a part, remove a row) are off while it reads, or null: the
 * form's reason, *Shared with you to read* unless it gave another (S12.19.1).
 */
export function useReadWhy() {
  const form = useContext(Reading);
  return typeof form === 'string' ? form : form ? READ_ONLY : null;
}
