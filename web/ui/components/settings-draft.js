// A Settings section's draft (requirements S12.15, S16): each of its keys is a record of the
// save's (`Setng`), changed where it is saved and made, when it changes, where it stands at its
// default. The section's form reads and sets its keys by name, through one view of them.
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { saveOne, useDraft } from './draft-form.js';

/** A setting: its key, and a value its definition checks; a password's is never read back. */
export class SettingRec extends Record {
  /** @override */
  static prefix = 'Setng';
  /** @override */
  static fields = FIELDS.SettingRecord;
}

/**
 * The section's keys as one: `get`, `set`, `revert` and `error` by key, and every refusal
 * named by its key.
 * @param {Map<string, SettingRec>} recs
 */
function byKey(recs) {
  const one = (/** @type {string} */ k) => {
    const r = recs.get(k);
    if (!r) throw new Error(`${k} is not a key of this section`);
    return r;
  };
  return {
    get: (/** @type {string} */ k) => one(k).get('value'),
    set: (/** @type {string} */ k, /** @type {any} */ v) => one(k).set('value', v),
    revert: (/** @type {string} */ k) => one(k).revert('value'),
    /** A refusal at the key's value, or at the key, which its definition names. */
    error: (/** @type {string} */ k) =>
      one(k).error('value') || one(k).error(k) || one(k).error(null),
    get errors() {
      return [...recs].flatMap(([k, r]) => r.errors.map((e) => ({ ...e, field: k })));
    },
  };
}

/**
 * A section's draft of its keys, read from the settings as `GET /settings` gave them; a
 * password among them starts empty.
 * @param {any} v  the settings as read
 * @param {string[]} keys
 */
export function useSettingsDraft(v, keys) {
  const read = v
    ? JSON.stringify(keys.map((k) => [k, v.records[k] || null, v.values[k] ?? null]))
    : '';
  const f = useDraft(
    (draft) => {
      if (!v) return;
      for (const key of keys) {
        const ref = v.records[key];
        const value = v.values[key] ?? null;
        if (ref) draft.load(SettingRec, { id: ref.id, version: ref.version, key, value });
        else draft.add(SettingRec, { key, value }, { optional: true });
      }
    },
    [read],
  );
  const recs = new Map(
    /** @type {SettingRec[]} */ (f.draft?.records || []).map((r) => [r.get('key'), r]),
  );
  // A draft read before the settings came holds none of the keys yet.
  const ready = f.draft && keys.every((k) => recs.has(k));
  return { ...f, rec: ready ? byKey(recs) : undefined };
}

/**
 * One key saved at once, as a choice that takes effect when made: the settings as `GET
 * /settings` gave them, the key, its new value.
 * @param {any} v @param {string} key @param {any} value
 */
export function saveSetting(v, key, value) {
  const ref = v.records[key];
  const row = ref ? { id: ref.id, version: ref.version, key, value: v.values[key] ?? null } : null;
  return saveOne(SettingRec, row, { key, value });
}
