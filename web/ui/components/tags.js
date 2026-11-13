// Tags (requirements S2.6): a person's own, each a record (`Tag`) that transactions, receipts
// and rules refer to by id, chosen as chips (S12.18.12); a name that is new makes its tag in the
// same draft, saved with the rest.
import { html } from '../app/html.js';
import { useList } from '../app/hooks.js';
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { Field } from '../kit/fields.js';
import { TagInput } from '../kit/tags.js';

/** A tag of the user's own. */
export class TagRec extends Record {
  /** @override */
  static prefix = 'Tag';
  /** @override */
  static fields = FIELDS.TagRecord;
}

/**
 * The tags field for a record's `tagIds` (S12.18.12): the record's tags as chips, the user's
 * own listed as they type, the most used first; a name not yet a tag makes one in the same
 * draft, saved with the rest, and one this draft made and no longer names goes with it.
 * @param {{ rec: import('../app/draft.js').Record, draft: import('../app/draft.js').Draft,
 *   label?: string, id?: string, hint?: string, placeholder?: string, disabled?: boolean,
 *   name?: string, autoGrow?: boolean }} p
 */
export function TagsField(
  { rec, draft, label = 'Tags', id, hint, placeholder, disabled, name = 'tagIds', autoGrow },
) {
  const list = useList('/tags');
  const saved = /** @type {any[]} */ (list.data) || [];
  // The tags this draft makes, beside the ones saved.
  const made = /** @type {TagRec[]} */ (draft.records.filter((r) => r instanceof TagRec));
  const items = [
    ...saved.map((t) => ({ key: t.id, label: t.name, uses: t.uses })),
    ...made.map((r) => ({ key: r.id, label: String(r.get('name') ?? ''), uses: 0 })),
  ];
  const ids = /** @type {string[]} */ (rec.get(name) || []);
  const set = (/** @type {string[]} */ keys) => {
    for (const r of made) if (!keys.includes(r.id)) draft.remove(r);
    rec.set(name, keys);
  };
  return html`
    <${Field} label=${label} id=${id} error=${rec.error(name)} hint=${hint}>
      <${TagInput} value=${ids} items=${items} onChange=${set} allowNew=${true}
        onCreate=${(/** @type {string} */ n) => draft.add(TagRec, { name: n.toLowerCase() }).id}
        placeholder=${placeholder} disabled=${disabled} autoGrow=${autoGrow} />
      </${Field}>
  `;
}
