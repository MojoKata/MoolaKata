/// <reference lib="deno.ns" />
// Editing records (requirements S12.15, S17.3.9): what a draft sends, puts back and saves.
import { countedIds, Draft, idMaker, isId, Record, typeOf } from '../app/draft.js';
import { Dec } from '../app/dec.js';
import { equal, truthy } from './assert.js';

const NOW = Date.UTC(2026, 9, 28, 14, 5);

class Txn extends Record {
  /** @override */
  static prefix = 'Txn';
  /** @override */
  static fields = {
    kind: { type: 'choice', choices: ['buy', 'transfer-in'] },
    amount: { type: 'money' },
    payee: { type: 'text', nullable: true },
    costBasis: { type: 'money', nullable: true },
    tags: { type: 'list', items: { type: 'text' }, set: true },
  };
  /** @override */
  static defaults = {
    kind: 'buy',
    amount: Dec.parse('0.00'),
    payee: null,
    costBasis: null,
    tags: [],
  };
  /** @override */
  static rules = {
    costBasis: { when: (/** @type {Txn} */ r) => r.get('kind') === 'transfer-in', otherwise: null },
  };
}

class Split extends Record {
  /** @override */
  static prefix = 'Split';
  /** @override */
  static fields = { transactionId: { type: 'ref', prefix: 'Txn' }, amount: { type: 'money' } };
  /** @override */
  static ownedBy = ['transactionId'];
}

const read = () => ({
  id: 'Txn_01k8nfgq4g0000000000000000',
  version: 3,
  kind: 'transfer-in',
  amount: Dec.parse('42.00'),
  payee: 'Broker',
  costBasis: Dec.parse('30.00'),
  tags: ['a', 'b'],
});

/** A draft whose saves are kept, with ids that repeat. @param {any} [answer] */
function draft(answer = { saved: [] }) {
  /** @type {any[]} */
  const sent = [];
  const d = new Draft({
    newId: countedIds(() => NOW),
    post: (body, key) => {
      sent.push({ body, key });
      if (answer instanceof Error) return Promise.reject(answer);
      return Promise.resolve(answer);
    },
  });
  return { d, sent };
}

Deno.test('values compare as values: 42 and 42.00 are the same amount', () => {
  const money = typeOf({ type: 'money' });
  truthy(money.equal(Dec.parse('42'), Dec.parse('42.00'), { type: 'money' }));
  equal(money.parse('$1,234.5', { type: 'money' }), { value: Dec.parse('1234.5') });
  truthy('error' in money.parse('1.234', { type: 'money' }), 'three places refused');
  equal(money.parse('(12.00)', { type: 'money' }), { value: Dec.parse('-12.00') });
  truthy('error' in typeOf({ type: 'int' }).parse('', { type: 'int' }), 'required');
  equal(typeOf({ type: 'int', nullable: true }).parse('', { type: 'int', nullable: true }), {
    value: null,
  });
});

Deno.test('a dialog saved untouched sends nothing', async () => {
  const { d, sent } = draft();
  const t = d.load(Txn, read());
  t.set('amount', Dec.parse('42'));
  t.input('payee', 'Broker');
  equal(d.changed, false);
  equal(d.ops(), []);
  equal(await d.save(), { status: 'saved', saved: [] });
  equal(sent.length, 0);
});

Deno.test('only what changed is sent, and set back it is unchanged again', () => {
  const { d } = draft();
  const t = d.load(Txn, read());
  t.input('amount', '50');
  equal(d.ops(), [{
    op: 'update',
    entity: 'Txn',
    id: t.id,
    version: 3,
    fields: { amount: Dec.parse('50') },
  }]);
  t.input('amount', '42.00');
  equal(t.changed, false);
  t.set('payee', 'Other');
  t.revert('payee');
  equal(t.get('payee'), 'Broker');
  equal(d.changed, false);
});

Deno.test('a set is sent as what to add and take away', () => {
  const { d } = draft();
  const t = d.load(Txn, read());
  t.set('tags', ['b', 'c']);
  equal(t.changes(), { tags: { add: ['c'], remove: ['a'] } });
  t.set('tags', ['b', 'a']);
  equal(t.changed, false, 'the same set in another order');
});

Deno.test('an edit a rule makes is put back with the edit that caused it', () => {
  const { d } = draft();
  const t = d.load(Txn, read());
  t.set('kind', 'buy');
  equal(t.get('costBasis'), null, 'the rule cleared it');
  equal(t.applies('costBasis'), false);
  equal(Object.keys(t.changes()).sort(), ['costBasis', 'kind']);
  t.revert('kind');
  equal(t.get('costBasis'), Dec.parse('30.00'));
  equal(t.changed, false);
});

Deno.test('a field that does not read keeps its error and the last value that did', () => {
  const { d } = draft();
  const t = d.load(Txn, read());
  equal(t.input('amount', '12.3.4'), false);
  truthy(t.error('amount'));
  equal(t.get('amount'), Dec.parse('42.00'));
  t.input('amount', '12.30');
  equal(t.error('amount'), null);
});

Deno.test('new records take ids made here, and refer to each other before any is saved', () => {
  const { d } = draft();
  const t = d.add(Txn, { amount: Dec.parse('10.00') });
  const s = d.add(Split, { transactionId: t.id, amount: Dec.parse('4.00') });
  truthy(isId(t.id, 'Txn') && isId(s.id, 'Split'));
  const ops = d.ops();
  equal(ops.map((o) => o.op), ['create', 'create']);
  equal(ops[1].fields, { transactionId: t.id, amount: Dec.parse('4.00') });
  equal(ops[0].fields.kind, 'buy', 'defaults are sent with a new record');
});

Deno.test('deleting a record deletes what it owns, and bringing it back brings them back', () => {
  const { d } = draft();
  const t = d.load(Txn, read());
  const s = d.load(Split, {
    id: 'Split_01k8nfgq4g0000000000000001',
    version: 1,
    transactionId: t.id,
    amount: Dec.parse('1.00'),
  });
  d.remove(t);
  truthy(s.removed);
  equal(d.ops().map((o) => [o.op, o.id]), [['delete', t.id], ['delete', s.id]]);
  d.unremove(t);
  equal(s.removed, false);
  equal(d.ops(), []);
});

Deno.test('a checkpoint puts back what a dialog opened from a dialog changed', () => {
  const { d } = draft();
  const t = d.load(Txn, read());
  t.set('payee', 'Kept');
  const m = d.mark();
  t.set('amount', Dec.parse('1.00'));
  d.add(Split, { transactionId: t.id, amount: Dec.parse('1.00') });
  truthy(d.changedSince(m));
  d.rollback(m);
  equal(d.changedSince(m), false);
  equal(t.get('payee'), 'Kept');
  equal(t.get('amount'), Dec.parse('42.00'));
  equal(d.records.length, 1);
});

Deno.test('questions are confirmed by name, and a retry keeps its key', async () => {
  const asked = Object.assign(new Error('Saving this asks first.'), {
    status: 409,
    code: 'confirm-needed',
    body: { asks: [{ code: 'closed-year', id: 'Txn_01k8nfgq4g0000000000000000', message: '…' }] },
    errors: [],
  });
  const { d, sent } = draft(asked);
  d.load(Txn, read()).set('payee', 'New');
  equal((await d.save()).status, 'asks');
  equal((await d.save()).status, 'asks');
  equal(sent[0].key, sent[1].key, 'the same ops keep their key');
  d.post = (body, key) => (sent.push({ body, key }), Promise.resolve({ saved: [{ id: 'x' }] }));
  equal((await d.save({ confirmAsks: true })).status, 'saved');
  equal(sent[2].body.confirm, [{ code: 'closed-year', id: 'Txn_01k8nfgq4g0000000000000000' }]);
  truthy(sent[2].key !== sent[1].key, 'other ops, another key');
});

Deno.test('a refusal lands on its record and field; a stale version saves nothing', async () => {
  const refused = Object.assign(new Error('Nothing was saved.'), {
    status: 422,
    code: 'save-refused',
    errors: [
      { id: 'Txn_01k8nfgq4g0000000000000000', field: 'amount', message: 'Too much.' },
      { field: null, message: 'Something else.' },
    ],
  });
  const { d } = draft(refused);
  const t = d.load(Txn, read());
  t.set('amount', Dec.parse('9.00'));
  equal((await d.save()).status, 'refused');
  equal(t.error('amount'), 'Too much.');
  equal(d.formError, 'Something else.');
  d.post = () => Promise.reject(Object.assign(new Error('stale'), { status: 412 }));
  equal(await d.save(), { status: 'stale' });
});

Deno.test('ids sort by when they were made, and repeat when counted', () => {
  let now = NOW;
  const make = idMaker({ now: () => now });
  const a = make('Txn'), b = make('Txn');
  now += 5;
  const c = make('Txn');
  truthy(a < b && b < c, 'in the order made');
  truthy(isId(a, 'Txn') && !isId(a, 'Split') && !isId('Txn_0', 'Txn'));
  const one = countedIds(() => NOW), two = countedIds(() => NOW);
  equal(one('Txn'), two('Txn'));
  truthy(one('Txn') !== two('Split'));
});

Deno.test('what is typed stays in its field while it is edited', () => {
  const { d } = draft();
  const t = d.load(Txn, read());
  equal(t.shown('amount'), '42.00');
  t.input('amount', '12.');
  equal(t.shown('amount'), '12.', 'kept as typed, even before it reads');
  t.input('amount', '12.5');
  equal([t.shown('amount'), t.get('amount')], ['12.5', Dec.parse('12.5')]);
  t.revert('amount');
  equal(t.shown('amount'), '42.00');
  t.input('amount', '9');
  t.set('amount', Dec.parse('7.00'));
  equal(t.shown('amount'), '7.00', 'a value set by code shows as that value');
});

Deno.test('text that does not read yet is a change, and is never sent', async () => {
  const { d, sent } = draft();
  const t = d.load(Txn, read());
  t.input('amount', '12.3.4');
  equal(d.changed, true, 'asked about before it is discarded');
  equal(d.ops(), []);
  equal((await d.save()).status, 'refused');
  equal(d.formError, 'Correct the fields marked first.', 'said above the buttons');
  equal(sent.length, 0);
  t.revert('amount');
  equal(d.changed, false);
});

Deno.test('a fingerprint tells the same changes from others', () => {
  const { d } = draft();
  const t = d.load(Txn, read());
  const none = d.fingerprint();
  t.set('payee', 'Bank');
  const one = d.fingerprint();
  truthy(one !== none);
  t.set('payee', 'Broker');
  equal(d.fingerprint(), none, 'set back, the same as untouched');
  t.input('amount', '42.0');
  equal(d.fingerprint(), none, '42.0 and 42.00 are the same amount');
});
