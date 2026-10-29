// Tags (requirements S2.6): a person's own, each a record (`Tag`) that transactions, receipts
// and rules refer to by id. The box is typed as names separated by commas; a name that is new
// makes its tag in the same draft, saved with the rest.
import { html } from '../app/html.js';
import { useList } from '../app/hooks.js';
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { Field, Input } from './fields.js';

/** A tag of the user's own. */
export class TagRec extends Record {
  /** @override */
  static prefix = 'Tag';
  /** @override */
  static fields = FIELDS.TagRecord;
}

/** Names as typed: trimmed, lower case, once each. @param {string} text */
const namesOf = (text) => [
  ...new Set(text.split(',').map((x) => x.trim().toLowerCase()).filter(Boolean)),
];

/**
 * The tags box for a record's `tagIds`: names in, ids kept.
 * @param {{ rec: import('../app/draft.js').Record, draft: import('../app/draft.js').Draft,
 *   label?: string, id?: string, hint?: string, placeholder?: string, disabled?: boolean,
 *   name?: string }} p
 */
export function TagsField(
  { rec, draft, label = 'Tags', id, hint, placeholder, disabled, name = 'tagIds' },
) {
  const list = useList('/tags');
  const saved = /** @type {any[]} */ (list.data) || [];
  // The tags this draft makes, by name, beside the ones saved.
  const made = /** @type {TagRec[]} */ (draft.records.filter((r) => r instanceof TagRec));
  const nameOf = (/** @type {string} */ tagId) =>
    saved.find((t) => t.id === tagId)?.name ?? made.find((r) => r.id === tagId)?.get('name');
  const ids = /** @type {string[]} */ (rec.get(name) || []);
  const shown = rec.typed(name) ?? ids.map(nameOf).filter(Boolean).join(', ');
  const type = (/** @type {string} */ text) => {
    const names = namesOf(text);
    const chosen = names.map((n) => {
      const have = saved.find((t) => t.name === n) || made.find((r) => r.get('name') === n);
      return have ? have.id : draft.add(TagRec, { name: n }).id;
    });
    // A tag this draft made and no longer names goes with it.
    for (const r of made) if (!chosen.includes(r.id)) draft.remove(r);
    rec.inputAs(name, text, () => ({ value: { [name]: chosen } }));
  };
  return html`
    <${Field} label=${label} id=${id} error=${rec.error(name)} hint=${hint}>
      <${Input} value=${shown} onInput=${type} placeholder=${placeholder}
        disabled=${disabled} />
      </${Field}>
  `;
}
