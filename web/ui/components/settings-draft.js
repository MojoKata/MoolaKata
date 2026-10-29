// Settings' keys and the tax tables in a screen's draft (requirements S12.15, S16): they are
// the server's own, not records of the save's, so a section's draft is saved by its own route,
// as the save would be: only what changed, against the version read, each refusal at its field.
import { api } from '../api/client.js';
import { Record } from '../app/draft.js';
import { useDraft } from './draft-form.js';

/** A section's values as one record of its draft: its fields the section's keys. */
export class SectionRec extends Record {
  /** @override */
  static prefix = 'Section';
}

/**
 * A section's draft of `values`, read at `version`, saved by `send(fields, version)`, which
 * answers with the section as read again.
 * @param {string} id  the section's name, the record's id
 * @param {{ version: number, values: { [key: string]: any } } | null} read
 * @param {(fields: any, version: number) => Promise<any>} send
 */
export function useSectionDraft(id, read, send) {
  /** @param {any} body */
  const post = async (body) => {
    const [op] = body.ops;
    try {
      const out = await send(op.fields, op.version);
      return { saved: [{ entity: op.entity, id: op.id, version: out.version, record: out }] };
    } catch (e) {
      // A refusal names the record, so it shows at its field.
      const err = /** @type {any} */ (e);
      if (err?.errors) err.errors = err.errors.map((/** @type {any} */ x) => ({ ...x, id }));
      throw e;
    }
  };
  return useDraft(
    (draft) => {
      if (read) draft.load(SectionRec, { id, version: read.version, ...read.values });
    },
    [id, read?.version, Object.keys(read?.values || {}).join()],
    { post },
  );
}

/**
 * A Settings section's draft of its keys, read from the settings as `GET /settings` gave them.
 * @param {any} v  the settings as read
 * @param {string[]} keys
 */
export function useSettingsDraft(v, keys) {
  const read = v
    ? { version: v.version, values: Object.fromEntries(keys.map((k) => [k, v.values[k]])) }
    : null;
  return useSectionDraft(
    'settings',
    read,
    (fields, version) => api.patch('/settings', fields, version),
  );
}
