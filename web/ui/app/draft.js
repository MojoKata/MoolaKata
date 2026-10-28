// Editing records (requirements S12.15, S17.3.9). A dialog edits a Draft of the records it read:
// each Record keeps its values (`data`) and, for each field changed, the value it had, so only
// what changed is sent, a field or the whole dialog can be put back, and an untouched dialog
// sends nothing. Save sends the whole draft in one request (S13.8.11), all or nothing.
//
// Field types come from the API's OpenAPI document (`api/fields.js`); an entity class extends
// Record with what only the browser needs (defaults, declared rules, values for display).

import { signal } from '@preact/signals-core';
import { Dec } from './dec.js';
import { api } from '../api/client.js';

/**
 * A field's type, as `api/fields.js` gives it.
 * @typedef {{ type: string, nullable?: boolean, choices?: any[], prefix?: string,
 *   items?: FieldSpec, set?: boolean, schema?: string }} FieldSpec
 */

/**
 * What a type does with a value: read typed text, show a value in an input, compare two values
 * as values, and write the API's form.
 * @typedef {{ parse: (text: string, spec: FieldSpec) => { value: any } | { error: string },
 *   format: (value: any, spec: FieldSpec) => string, equal: (a: any, b: any, spec: FieldSpec) =>
 *   boolean, wire: (value: any, spec: FieldSpec) => any }} FieldType
 */

const same = (/** @type {any} */ a, /** @type {any} */ b) => a === b;
const asIs = (/** @type {any} */ v) => v;
const text = (/** @type {any} */ v) => (v == null ? '' : String(v));

/** @param {RegExp} shape @param {string} hint @param {(t: string) => any} [read] */
function shaped(shape, hint, read = asIs) {
  return /** @type {FieldType} */ ({
    parse: (t) => (shape.test(t.trim()) ? { value: read(t.trim()) } : { error: hint }),
    format: text,
    equal: same,
    wire: asIs,
  });
}

/** An exact decimal, with at most `places` places when given. @param {number | null} places */
function decimal(places) {
  return /** @type {FieldType} */ ({
    parse(t) {
      let s = t.replace(/[$,\s]/g, '');
      const paren = /^\((.*)\)$/.exec(s);
      if (paren) s = '-' + paren[1];
      const m = /^[+-]?\d+(?:\.(\d*))?$/.exec(s);
      if (!m) {
        return { error: places === 2 ? 'Type an amount, such as 1,234.50.' : 'Type a number.' };
      }
      if (places !== null && (m[1] || '').length > places) {
        return { error: `At most ${places} places.` };
      }
      return { value: Dec.parse(s) };
    },
    format: (
      v,
    ) => (v == null
      ? ''
      : places === null
      ? Dec.of(v).toString()
      : Dec.of(v).round(places).toString()),
    equal: (a, b) => Dec.of(a).eq(Dec.of(b)),
    wire: (v) => Dec.of(v),
  });
}

/** JSON with its keys in order, so two values that mean the same compare the same. */
function canonical(/** @type {any} */ v) {
  return JSON.stringify(
    v,
    (_k, x) =>
      x && typeof x === 'object' && !Array.isArray(x) && !(x instanceof Dec)
        ? Object.fromEntries(Object.entries(x).sort(([a], [b]) => (a < b ? -1 : 1)))
        : x,
  );
}

/** @type {{ [name: string]: FieldType }} */
export const TYPES = {
  text: { parse: (t) => ({ value: t }), format: text, equal: same, wire: asIs },
  timestamp: { parse: (t) => ({ value: t }), format: text, equal: same, wire: asIs },
  money: decimal(2),
  quantity: decimal(null),
  percent: decimal(null),
  int: shaped(/^[+-]?\d+$/, 'Type a whole number.', Number),
  bool: {
    parse: (
      t,
    ) => (t === 'true' || t === 'false' ? { value: t === 'true' } : { error: 'Yes or no.' }),
    format: (v) => (v ? 'true' : 'false'),
    equal: same,
    wire: asIs,
  },
  date: shaped(/^\d{4}-\d{2}-\d{2}$/, 'Type a date, such as 2026-10-28.'),
  month: shaped(/^\d{4}-\d{2}$/, 'Type a month, such as 2026-10.'),
  choice: {
    parse: (t, spec) =>
      (spec.choices || []).includes(t) ? { value: t } : { error: 'Choose one of the list.' },
    format: text,
    equal: same,
    wire: asIs,
  },
  ref: {
    parse: (t, spec) =>
      isId(t.trim(), spec.prefix || '') ? { value: t.trim() } : { error: 'Not one of these.' },
    format: text,
    equal: same,
    wire: asIs,
  },
  list: {
    parse: () => ({ error: 'A list is chosen, not typed.' }),
    format: (v) => (v || []).join(', '),
    equal(a, b, spec) {
      const item = typeOf(spec.items || { type: 'json' });
      const one = (/** @type {any} */ x, /** @type {any} */ y) =>
        item.equal(x, y, spec.items || { type: 'json' });
      if (a.length !== b.length) return false;
      if (spec.set) {
        return a.every((/** @type {any} */ x) => b.some((/** @type {any} */ y) => one(x, y)));
      }
      return a.every((/** @type {any} */ x, /** @type {number} */ i) => one(x, b[i]));
    },
    wire: (v, spec) =>
      v.map((/** @type {any} */ x) =>
        typeOf(spec.items || { type: 'json' }).wire(x, spec.items || { type: 'json' })
      ),
  },
  json: {
    parse: (t) => {
      try {
        return { value: JSON.parse(t) };
      } catch {
        return { error: 'Not valid.' };
      }
    },
    format: (v) => (v == null ? '' : JSON.stringify(v)),
    equal: (a, b) => canonical(a) === canonical(b),
    wire: asIs,
  },
};

/** A field's type, with empty values handled for every type. @param {FieldSpec} spec */
export function typeOf(spec) {
  const t = TYPES[spec.type] || TYPES.json;
  return /** @type {FieldType} */ ({
    parse(input, s) {
      if (String(input ?? '').trim() === '' && spec.type !== 'text') {
        return s.nullable ? { value: null } : { error: 'Required.' };
      }
      return t.parse(String(input), s);
    },
    format: (v, s) => (v == null ? '' : t.format(v, s)),
    equal: (a, b, s) => (a == null || b == null ? a == null && b == null : t.equal(a, b, s)),
    wire: (v, s) => (v == null ? null : t.wire(v, s)),
  });
}

// ---------- ids (schema.md §2) ----------

const ALPHABET = '0123456789abcdefghjkmnpqrstvwxyz';

/** A UUIDv7's 128 bits as the 26 characters ids use. @param {bigint} n */
function encode(n) {
  let out = '';
  for (let i = 0; i < 26; i++) {
    out = ALPHABET[Number(n & 31n)] + out;
    n >>= 5n;
  }
  return out;
}

/** Whether a value is an id of a table, in its one spelling. @param {string} value @param {string} prefix */
export function isId(value, prefix) {
  return new RegExp(`^${prefix}_[0-7][${ALPHABET}]{25}$`).test(String(value));
}

/** @param {bigint} ms @param {bigint} a @param {bigint} b */
function uuid7(ms, a, b) {
  return (ms << 80n) | (7n << 76n) | ((a & 0xfffn) << 64n) | (2n << 62n) | (b & ((1n << 62n) - 1n));
}

/** @param {Uint8Array} bytes */
function bigOf(bytes) {
  return bytes.reduce((n, x) => (n << 8n) | BigInt(x), 0n);
}

/**
 * Ids as the server makes them, from this computer's clock: a UUIDv7 with a counter that keeps
 * ids made in the same millisecond in order.
 * @param {{ now?: () => number, random?: (n: number) => Uint8Array }} [o]
 * @returns {(prefix: string) => string}
 */
export function idMaker(o = {}) {
  const now = o.now || (() => Date.now());
  const random = o.random || ((n) => crypto.getRandomValues(new Uint8Array(n)));
  let last = 0n, counter = 0n;
  return (prefix) => {
    let ms = BigInt(now());
    if (ms <= last) {
      ms = last;
      counter += 1n;
      if (counter > 0xfffn) [ms, counter] = [last + 1n, 0n];
    } else counter = bigOf(random(2)) & 0x3ffn;
    last = ms;
    return `${prefix}_${encode(uuid7(ms, counter, bigOf(random(8))))}`;
  };
}

/** FNV-1a, 64 bits: a repeatable stand-in for chance. @param {string} s */
function fnv(s) {
  let h = 0xcbf29ce484222325n;
  for (const c of new TextEncoder().encode(s)) {
    h = ((h ^ BigInt(c)) * 0x100000001b3n) & ((1n << 64n) - 1n);
  }
  return h;
}

/**
 * Ids that repeat from run to run (tests, the generated mockup's build): a count per prefix,
 * kept apart from the server's own count, at the time `now` gives.
 * @param {() => number} now
 * @returns {(prefix: string) => string}
 */
export function countedIds(now) {
  /** @type {Map<string, number>} */
  const counts = new Map();
  return (prefix) => {
    const n = (counts.get(prefix) || 0) + 1;
    counts.set(prefix, n);
    return `${prefix}_${encode(uuid7(BigInt(now()), BigInt(n), fnv(`browser:${prefix}${n}`)))}`;
  };
}

// ---------- Record ----------

/**
 * A rule an entity class declares for a field (S17.3.9.3): it applies only `when`, and is
 * `otherwise` when it doesn't; or it is `requiredWhen`; or it is set to `value` when `setWhen`.
 * @typedef {{ when?: (r: any) => boolean, otherwise?: any, requiredWhen?: (r: any) => boolean,
 *   setWhen?: (r: any) => boolean, value?: any }} Rule
 */

let serial = 0;

/** One record a dialog edits (S17.3.9.1). Entity classes extend it. */
export class Record {
  /** The table's prefix (`schema.md` §3). */
  static prefix = '';
  /** The fields, from `api/fields.js`. @type {{ [name: string]: FieldSpec }} */
  static fields = {};
  /** Values a new record starts with. @type {{ [name: string]: any }} */
  static defaults = {};
  /** @type {{ [name: string]: Rule }} */
  static rules = {};
  /** Reference fields whose record owns this one: deleted with it (`schema.md` §4). */
  static ownedBy = /** @type {string[]} */ ([]);
  /**
   * For a kind whose records are taken out by a change rather than deleted (a plan line set to
   * nothing from a month on): the fields a removed record sends as an update.
   * @type {((r: any) => { [name: string]: any }) | null}
   */
  static removal = null;

  /** @type {{ [name: string]: any }} */
  #data;
  /** For each field changed: the value it had, and the field whose change caused it. */
  #modified = /** @type {Map<string, { was: any, cause: string | null }>} */ (new Map());
  #tick = signal(0);
  /** @type {Map<string | null, string>} */
  #errors = new Map();
  /** What was typed in a field, kept as typed while it is being edited. @type {Map<string, string>} */
  #typed = new Map();

  /**
   * @param {string} id
   * @param {{ [name: string]: any }} data
   * @param {{ state?: 'new' | 'read', version?: number }} [o]
   */
  constructor(id, data, o = {}) {
    this.id = id;
    this.state = o.state || 'read';
    this.version = o.version ?? data.version ?? 0;
    this.removed = false;
    /** The record whose removal removed this one. @type {string | null} */
    this.removedBy = null;
    this.key = ++serial;
    this.#data = { ...data };
  }

  /** @returns {typeof Record} */
  get cls() {
    return /** @type {any} */ (this.constructor);
  }

  /** @param {string} name */
  spec(name) {
    return this.cls.fields[name] || { type: 'json', nullable: true };
  }

  /** @param {string} name */
  get(name) {
    this.#tick.value;
    return this.#data[name];
  }

  /** Whether a field applies, by its declared rule. @param {string} name */
  applies(name) {
    const rule = this.cls.rules[name];
    return !rule?.when || rule.when(this);
  }

  /** Whether a field must have a value, by its declared rule. @param {string} name */
  required(name) {
    const rule = this.cls.rules[name];
    return !!rule?.requiredWhen?.(this) || (this.applies(name) && !this.spec(name).nullable);
  }

  /**
   * Set a field. A value equal to the one it had makes the field unchanged again. The declared
   * rules then run, their edits tied to this field.
   * @param {string} name @param {any} value @param {string | null} [cause]
   */
  set(name, value, cause = null) {
    const spec = this.spec(name), t = typeOf(spec);
    if (t.equal(this.#data[name], value, spec)) return;
    if (cause !== null || !this.#inputting) this.#typed.delete(name);
    const m = this.#modified.get(name);
    if (!m) this.#modified.set(name, { was: this.#data[name], cause });
    this.#data[name] = value;
    const back = this.#modified.get(name);
    if (back && t.equal(back.was, value, spec)) this.#modified.delete(name);
    this.#errors.delete(name);
    if (cause === null) {
      this.#rules(name);
      this.onSet(name, value);
    }
    this.#tick.value++;
  }

  /** Set a field from what was typed; a value that doesn't read is the field's error. @param {string} name @param {string} input */
  input(name, input) {
    const spec = this.spec(name), r = typeOf(spec).parse(input, spec);
    this.#typed.set(name, input);
    if ('error' in r) {
      this.#unread.add(name);
      this.#errors.set(name, r.error);
      this.#tick.value++;
      return false;
    }
    this.#unread.delete(name);
    this.#inputting = true;
    try {
      this.set(name, r.value);
    } finally {
      this.#inputting = false;
    }
    this.#errors.delete(name);
    this.#tick.value++;
    return true;
  }

  #inputting = false;
  /** Fields whose typed text doesn't read yet: a change too, not to be lost unasked. */
  #unread = new Set();

  /** What a field shows in its input: what was typed there, else its value. @param {string} name */
  shown(name) {
    this.#tick.value;
    const typed = this.#typed.get(name);
    if (typed !== undefined) return typed;
    const spec = this.spec(name);
    return typeOf(spec).format(this.#data[name], spec);
  }

  /**
   * A hook an entity class may override, run after a person's edit: for what a declared rule
   * can't say (S17.3.9.3). Its own edits pass the field as their cause.
   * @param {string} _name @param {any} _value
   */
  onSet(_name, _value) {}

  /** The declared rules after an edit of `cause`. @param {string} cause */
  #rules(cause) {
    for (let pass = 0; pass < 8; pass++) {
      let moved = false;
      for (const [name, rule] of Object.entries(this.cls.rules)) {
        const spec = this.spec(name), t = typeOf(spec);
        /** @type {[boolean, any] | null} */
        let want = null;
        if (rule.when && !rule.when(this)) want = [true, rule.otherwise ?? null];
        else if (rule.setWhen?.(this)) want = [true, rule.value];
        if (want && !t.equal(this.#data[name], want[1], spec)) {
          this.set(name, want[1], cause);
          moved = true;
        }
      }
      if (!moved) return;
    }
  }

  /** Put a field back, with the edits its change caused. @param {string} name */
  revert(name) {
    for (const [other, m] of [...this.#modified]) if (m.cause === name) this.revert(other);
    const m = this.#modified.get(name);
    if (m) this.#data[name] = m.was;
    this.#modified.delete(name);
    this.#errors.delete(name);
    this.#typed.delete(name);
    this.#unread.delete(name);
    this.#tick.value++;
  }

  /** Put every field back. */
  revertAll() {
    for (const [name, m] of this.#modified) this.#data[name] = m.was;
    this.#modified.clear();
    this.#errors.clear();
    this.#typed.clear();
    this.#unread.clear();
    this.#tick.value++;
  }

  /** Whether a field holds typed text that doesn't read yet. */
  get unread() {
    this.#tick.value;
    return this.#unread.size > 0;
  }

  /** @param {string} name */
  isChanged(name) {
    this.#tick.value;
    return this.#modified.has(name);
  }

  /** Whether the record holds changes: what the save would send, or text typed that doesn't
   * read yet. */
  get changed() {
    this.#tick.value;
    if (this.state === 'new') return !this.removed;
    return this.removed || this.#modified.size > 0 || this.#unread.size > 0;
  }

  /** The fields to send: every field for a new record, only those changed otherwise, a set's as what to add and take away. */
  changes() {
    /** @type {{ [name: string]: any }} */
    const out = {};
    const names = this.state === 'new' ? Object.keys(this.#data) : [...this.#modified.keys()];
    for (const name of names) {
      if (name === 'id' || name === 'version') continue;
      const spec = this.spec(name), t = typeOf(spec), v = this.#data[name];
      if (this.state !== 'new' && spec.type === 'list' && spec.set) {
        const was = this.#modified.get(name)?.was || [], now = v || [];
        const item = spec.items || { type: 'json' }, it = typeOf(item);
        const has = (/** @type {any[]} */ xs, /** @type {any} */ x) =>
          xs.some((y) => it.equal(x, y, item));
        out[name] = {
          add: now.filter((/** @type {any} */ x) => !has(was, x)).map((/** @type {any} */ x) =>
            it.wire(x, item)
          ),
          remove: was.filter((/** @type {any} */ x) => !has(now, x)).map((/** @type {any} */ x) =>
            it.wire(x, item)
          ),
        };
      } else out[name] = t.wire(v, spec);
    }
    return out;
  }

  /** The refusal at a field (`null` for the record as a whole). @param {string | null} name */
  error(name) {
    this.#tick.value;
    return this.#errors.get(name) || null;
  }

  /** @param {string | null} name @param {string} message */
  refuse(name, message) {
    this.#errors.set(name, message);
    this.#tick.value++;
  }

  /** Everything needed to come back to this point (a checkpoint, S12.15.7). */
  snapshot() {
    return {
      data: { ...this.#data },
      modified: new Map(this.#modified),
      removed: this.removed,
      removedBy: this.removedBy,
    };
  }

  /** @param {ReturnType<Record['snapshot']>} s */
  restore(s) {
    this.#data = { ...s.data };
    this.#modified = new Map(s.modified);
    this.removed = s.removed;
    this.removedBy = s.removedBy;
    this.#errors.clear();
    this.#typed.clear();
    this.#unread.clear();
    this.#tick.value++;
  }

  bump() {
    this.#tick.value++;
  }
}

// ---------- Draft ----------

/**
 * What a save came to: saved, a list of questions to confirm, refused (each reason on its
 * record and field), or stale (nothing saved: reload, S12.15.5).
 * @typedef {{ status: 'saved', saved: any[] } | { status: 'asks', asks: any[] } |
 *   { status: 'refused', message: string } | { status: 'stale' }} Outcome
 */

/**
 * The records one dialog edits (S17.3.9.5), saved together in one request.
 */
export class Draft {
  /** @type {Map<string, Record>} */
  #records = new Map();
  #tick = signal(0);
  /** The questions the last save asked (S12.15.4). @type {any[]} */
  asks = [];
  /** A refusal that belongs to no record. @type {string | null} */
  formError = null;
  #lastBody = '';
  #key = '';

  /**
   * @param {{ post?: (body: any, key: string) => Promise<any>, newId?: (prefix: string) => string }} [o]
   */
  constructor(o = {}) {
    this.post = o.post || ((body, key) => api.post('/save', body, { idempotent: key }));
    this.newId = o.newId || idMaker();
  }

  /**
   * A record as the route that saves it read it.
   * @template {Record} T @param {new (...a: any[]) => T} Cls @param {{ [name: string]: any }} data
   * @returns {T}
   */
  load(Cls, data) {
    const r = new Cls(data.id, data, { state: 'read', version: data.version });
    this.#records.set(r.id, r);
    this.#tick.value++;
    return r;
  }

  /**
   * A new record, its id made here so other records of the draft can refer to it.
   * @template {Record} T @param {new (...a: any[]) => T} Cls @param {{ [name: string]: any }} [data]
   * @returns {T}
   */
  add(Cls, data = {}) {
    const C = /** @type {typeof Record} */ (/** @type {any} */ (Cls));
    const r = new Cls(this.newId(C.prefix), { ...C.defaults, ...data }, { state: 'new' });
    this.#records.set(r.id, r);
    this.#tick.value++;
    return r;
  }

  /** @param {string} id */
  get(id) {
    return this.#records.get(id) || null;
  }

  /** Every record, in the order they were read or made. */
  get records() {
    this.#tick.value;
    return [...this.#records.values()];
  }

  /** The records that refer to `id` through a field marked as owned by it. @param {string} id */
  #owned(id) {
    return this.records.filter((r) => r.cls.ownedBy.some((f) => r.get(f) === id));
  }

  /** Delete a record, and what it owns with it. @param {Record} r @param {string | null} [by] */
  remove(r, by = null) {
    if (r.removed) return;
    r.removed = true;
    r.removedBy = by;
    r.bump();
    for (const o of this.#owned(r.id)) this.remove(o, r.id);
    this.#tick.value++;
  }

  /** Bring a deleted record back, with what went with it. @param {Record} r */
  unremove(r) {
    r.removed = false;
    r.removedBy = null;
    r.bump();
    for (const o of this.records) if (o.removedBy === r.id) this.unremove(o);
    this.#tick.value++;
  }

  /** Whether the save would send anything (S12.15.6). */
  get changed() {
    return this.records.some((r) => r.changed);
  }

  /** Put every record back as it was read; new ones go. */
  revertAll() {
    for (const r of this.records) {
      if (r.state === 'new') this.#records.delete(r.id);
      else {
        r.revertAll();
        if (r.removed) this.unremove(r);
      }
    }
    this.#tick.value++;
  }

  /** A checkpoint, for a dialog opened from a dialog (S12.15.7). */
  mark() {
    return new Map(this.records.map((r) => [r.id, { r, s: r.snapshot() }]));
  }

  /** Back to a checkpoint: what changed since is put back, records made since go. @param {ReturnType<Draft['mark']>} m */
  rollback(m) {
    for (const r of this.records) {
      const at = m.get(r.id);
      if (!at) this.#records.delete(r.id);
      else r.restore(at.s);
    }
    this.#tick.value++;
  }

  /** Whether anything changed since a checkpoint. @param {ReturnType<Draft['mark']>} m */
  changedSince(m) {
    const now = this.mark();
    if (now.size !== m.size) return true;
    for (const [id, { s }] of now) {
      const at = m.get(id);
      if (!at || at.s.removed !== s.removed || canonical(at.s.data) !== canonical(s.data)) {
        return true;
      }
    }
    return false;
  }

  /** The ops the save sends (S13.8.11.1): creates, updates and deletes. */
  ops() {
    /** @type {any[]} */
    const ops = [];
    for (const r of this.records) {
      const entity = r.cls.prefix;
      if (r.state === 'new') {
        if (!r.removed) ops.push({ op: 'create', entity, id: r.id, fields: r.changes() });
      } else if (r.removed) {
        const removal = r.cls.removal?.(r);
        ops.push(
          removal
            ? { op: 'update', entity, id: r.id, version: r.version, fields: removal }
            : { op: 'delete', entity, id: r.id, version: r.version },
        );
      } else {
        const fields = r.changes();
        if (Object.keys(fields).length) {
          ops.push({ op: 'update', entity, id: r.id, version: r.version, fields });
        }
      }
    }
    return ops;
  }

  /**
   * Save the draft. `confirmAsks` confirms the questions the last save asked, by name.
   * @param {{ confirmAsks?: boolean }} [o]
   * @returns {Promise<Outcome>}
   */
  async save(o = {}) {
    // Nothing is sent while a field holds text that doesn't read: its reason is at the field.
    if (this.records.some((r) => !r.removed && r.unread)) {
      return { status: 'refused', message: 'Correct the fields marked first.' };
    }
    const ops = this.ops();
    if (!ops.length) return { status: 'saved', saved: [] };
    const confirm = o.confirmAsks ? this.asks.map((a) => ({ code: a.code, id: a.id })) : [];
    const body = { ops, confirm };
    // A retry of the same ops keeps its key, so a lost answer can't save twice (S13.8.8).
    const text = canonical(body);
    if (text !== this.#lastBody || !this.#key) {
      [this.#lastBody, this.#key] = [text, crypto.randomUUID()];
    }
    this.formError = null;
    try {
      const answer = await this.post(body, this.#key);
      this.asks = [];
      return { status: 'saved', saved: answer?.saved || [] };
    } catch (e) {
      const err = /** @type {any} */ (e);
      if (err?.status === 412) return { status: 'stale' };
      if (err?.status === 409 && err.code === 'confirm-needed') {
        this.asks = err.body?.asks || [];
        this.#tick.value++;
        return { status: 'asks', asks: this.asks };
      }
      if (!err?.status) throw e;
      for (const x of err.errors || []) {
        const r = x.id ? this.get(x.id) : null;
        if (r) r.refuse(x.field, x.message);
        else this.formError = x.message;
      }
      if (!(err.errors || []).length) this.formError = err.message;
      this.#tick.value++;
      return { status: 'refused', message: err.message };
    }
  }
}
