// Adding or editing a transaction (requirements S2.6): payee, category, memo, tags and splits;
// for an investing account, trades with their instrument, quantity, price and fees; for a
// retirement account, the contribution year and who contributed.
import { useEffect, useState } from 'preact/hooks';
import { useList } from '../app/hooks.js';
import { ACCEPT, ReceiptLinkRec, uploadAll } from '../components/receipt.js';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { FIELDS } from '../api/fields.js';
import { canAdd, Record } from '../app/draft.js';
import { Dec } from '../app/dec.js';
import { DraftDialog, RecField, useDraft } from '../components/draft-form.js';
import { useDialogGuide } from '../components/help.js';
import { NewRuleDialog } from '../components/rules.js';
import { Field, Seg, Switch, SwitchRow, TypedInput } from '../components/fields.js';
import { Icon } from '../components/icon.js';
import { money, today } from '../app/format.js';
import { CategoryField } from '../components/categories.js';
import { BY_TYPE } from '../account-types/index.js';
import { TagsField } from '../components/tags.js';
import { confirmAction } from '../components/confirm.js';
import { openDialog } from '../components/dialog.js';

const BANK_KINDS = /** @type {[string, string][]} */ ([
  ['withdrawal', 'Money out'],
  ['deposit', 'Money in'],
  ['transfer', 'Transfer'],
  ['interest', 'Interest'],
  ['fee', 'Fee'],
]);
const TRADE_KINDS = /** @type {[string, string][]} */ ([
  ['buy', 'Buy'],
  ['sell', 'Sell'],
  ['dividend', 'Dividend'],
  ['reinvest', 'Reinvested dividend'],
  ['interest', 'Interest'],
  ['capital-gain', 'Capital-gain distribution'],
  ['transfer-in', 'Shares transferred in'],
  ['transfer-out', 'Shares transferred out'],
  ['reward', 'Coins received as income'],
  ['foreign-tax', 'Foreign tax paid'],
  ['deposit', 'Cash in'],
  ['withdrawal', 'Cash out'],
  ['fee', 'Fee'],
]);
const TRADE = ['buy', 'sell', 'reinvest', 'transfer-in', 'transfer-out', 'reward'];

/**
 * The owner's own contribution to a traditional IRA, which is deductible or not (S8.6): money
 * in, not an employer's, a rollover's or a conversion's.
 * @param {Txn} r
 */
const contributes = (r) => {
  const amount = r.get('amount');
  return r.typeOf(r.get('accountId')) === 'ira' &&
    ['deposit', 'transfer'].includes(r.get('kind')) &&
    amount != null && !Dec.of(amount).isNegative() && !Dec.of(amount).isZero() &&
    [null, '', 'employee'].includes(r.get('contributionSource') ?? null);
};

const DEDUCTIBLE = /** @type {[string, string][]} */ ([
  ['', 'Not decided'],
  ['yes', 'Deductible'],
  ['no', 'Not deductible'],
]);

/**
 * Whether a contribution, or a part of it, is deductible (S8.6): a nullable boolean, not
 * decided until chosen, and never read as deductible.
 * @param {{ rec: import('../app/draft.js').Record, label: string, id: string }} p
 */
function Deductible({ rec, label, id }) {
  const v = rec.get('deductible');
  return html`
    <${Field} label=${label} help="deductible" id=${id} error=${rec.error('deductible')}>
      <${Seg} label=${label} value=${v == null ? '' : v ? 'yes' : 'no'} options=${DEDUCTIBLE}
        onChange=${(/** @type {string} */ x) =>
          rec.set('deductible', x === '' ? null : x === 'yes')} />
      </${Field}>
  `;
}

/**
 * A transaction as its dialog's draft edits it (S2.6, S12.15). Its parts are records of their
 * own (`Part`), so each keeps its id, and what pays it back with it (S2.9).
 */
export class Txn extends Record {
  /** @override */
  static prefix = 'Txn';
  /** @override */
  static fields = FIELDS.TxnRecord;
  /** @override */
  static defaults = {
    kind: 'withdrawal',
    payee: null,
    memo: null,
    categoryId: null,
    tagIds: [],
    leftOutOf: [],
    cleared: false,
  };
  /** @override */
  static rules = {
    // A transfer-in's basis is typed with it (S2.6); the one paid back is named (S2.9).
    costBasis: { when: (/** @type {Txn} */ r) => r.get('kind') === 'transfer-in' },
    owedBy: { when: (/** @type {Txn} */ r) => r.get('reimbursable') != null },
    // A trade's fees are typed, 0 for none; other money has none (R3.11).
    fees: { when: (/** @type {Txn} */ r) => TRADE.includes(r.get('kind')) },
    // Only a contribution to a traditional IRA is deductible or not (S8.6).
    deductible: { when: contributes },
  };
  /** The kinds an account's type takes. @type {(accountId: string) => string[]} */
  kindsOf = () => [];
  /** An account's type. @type {(accountId: string) => string | undefined} */
  typeOf = () => undefined;

  /**
   * A new transaction's account takes a kind its type has: its first, otherwise. A kind that
   * is a trade starts its fees at 0, filled in as if typed: cleared, they stay blank and are
   * refused, never read as none (R3.11). @override
   */
  onSet(/** @type {string} */ name) {
    if (name === 'accountId') {
      const kinds = this.kindsOf(this.get('accountId'));
      if (!kinds.includes(this.get('kind'))) this.set('kind', kinds[0], 'accountId');
    }
    if ((name === 'accountId' || name === 'kind') && TRADE.includes(this.get('kind'))) {
      if (this.get('fees') == null) this.set('fees', '0', name);
    }
  }
}

/** A part of a transaction's amount with its own category (S2.6). */
class Part extends Record {
  /** @override */
  static prefix = 'Split';
  /** @override */
  static fields = FIELDS.SplitRecord;
  /** @override */
  static defaults = {
    categoryId: null,
    memo: null,
    reimbursable: null,
    owedBy: null,
    deductible: null,
  };
  /** @override */
  static ownedBy = ['transactionId'];
}

/** How much of a lot a sale takes, picked (S2.3, specific identification): a record of the sale. */
class Pick extends Record {
  /** @override */
  static prefix = 'LotPk';
  /** @override */
  static fields = FIELDS.LotPickRecord;
  /** @override */
  static defaults = { quantity: null };
  /** @override */
  static ownedBy = ['saleId'];
}

/**
 * `start` fills a new transaction, such as a trade a statement shows but doesn't read
 * (S1.3.3.8).
 * @param {{ close: (v?: any) => void, txn?: any, start?: any, accounts: any[],
 *   accountId?: string }} p
 */
export function TransactionDialog({ close, txn, start, accounts, accountId }) {
  useDialogGuide('dialog-transaction');
  const editing = !!txn;
  const readOnly = editing && !txn.access.writable;
  const writable = accounts.filter((a) => canAdd('Txn', a));
  const kindsOf = (/** @type {string} */ id) => {
    const type = BY_TYPE[accounts.find((a) => a.id === id)?.type] || BY_TYPE.checking;
    return (type.investing ? TRADE_KINDS : BANK_KINDS).map(([k]) => k);
  };
  const f = useDraft(async (draft) => {
    if (editing) {
      const got = await api.get(`/transactions/${txn.id}`);
      draft.load(Txn, { ...got, transferWithId: got.transferId });
      const t = /** @type {Txn} */ (draft.records[0]);
      for (const sp of t.get('splits') || []) draft.load(Part, { ...sp, transactionId: t.id });
      for (const p of got.picks || []) draft.load(Pick, { ...p, saleId: t.id });
      return;
    }
    const acct = accountId || writable[0]?.id || '';
    const kind = kindsOf(acct)[0];
    const t = draft.add(Txn, {
      accountId: acct,
      date: today(),
      kind,
      fees: TRADE.includes(kind) ? '0' : null,
    });
    // What a statement shows, typed in as a person would type it.
    for (const [k, v] of Object.entries(start || {})) {
      if (k in Txn.fields && v !== '' && v != null) t.input(k, String(v));
    }
  }, [txn?.id]);
  const draft = f.draft;
  const t = /** @type {Txn | undefined} */ (draft?.records.find((r) => r instanceof Txn));
  if (t) {
    t.kindsOf = kindsOf;
    t.typeOf = (id) => accounts.find((a) => a.id === id)?.type;
  }
  const parts = /** @type {Part[]} */ (
    (draft?.records || []).filter((r) => r instanceof Part && !r.removed)
  );
  const account = accounts.find((a) => a.id === t?.get('accountId')) || { type: 'checking' };
  const type = BY_TYPE[account.type] || BY_TYPE.checking;
  const kind = t?.get('kind') || '';
  const trade = TRADE.includes(kind);
  const total = parts.reduce((x, r) => x.add(Dec.of(r.get('amount') ?? 0)), Dec.parse('0'));
  const left = t && t.get('amount') != null ? Dec.of(t.get('amount')).sub(total) : total.neg();
  const deleting = !!t?.removed;
  /** Split…: a part, the category moving to the parts, and the marks with them. */
  const addPart = () => {
    if (!t || !draft) return;
    if (!parts.length) {
      t.set('categoryId', null);
      t.set('reimbursable', null);
      if (t.applies('deductible')) t.set('deductible', null);
    }
    draft.add(Part, { transactionId: t.id, amount: null });
  };
  return html`
    <${DraftDialog} f=${f} close=${close} what="This transaction"
      title=${readOnly ? 'Transaction' : editing ? 'Edit transaction' : 'Add transaction'}
      done=${deleting ? 'Deleted' : editing ? 'Saved' : 'Added'}
      label=${editing ? 'Save' : 'Add'}
      confirm=${deleting ? 'Delete it anyway' : 'Change it anyway'}
      hideSave=${readOnly && !draft?.changed}
      extra=${({ save }) =>
        readOnly
          ? html`<button type="button" class="btn" onClick=${() => close()}>Close</button>`
          : html`
            ${editing
              ? html`
                <button type="button" class="btn danger" disabled=${save.busy || !t || !draft}
                  onClick=${async () => {
                    if (!t || !draft) return;
                    const withStock = ['assign', 'exercise'].includes(txn.kind);
                    const sure = await confirmAction({
                      title: withStock
                        ? 'Delete this transaction and its stock trade?'
                        : 'Delete this transaction?',
                    });
                    if (!sure) return;
                    draft.remove(t);
                    const r = await save.run().catch(() => null);
                    // Refused or stale, it stays: only a question keeps the delete waiting.
                    if (r?.status !== 'asks' && r?.status !== 'saved') draft.unremove(t);
                  }}>Delete</button>
              `
              : null}
            ${editing && txn.transferId
              ? html`<button type="button" class="btn" disabled=${
                save.busy || !t
              } onClick=${async () => {
                // Enabled once the transaction's draft is loaded, so a click is never lost.
                if (!t) return;
                // The match undone through the save, with whatever else was changed here.
                t.set('transferWithId', null);
                const r = await save.run().catch(() => null);
                if (r?.status !== 'asks' && r?.status !== 'saved') t.revert('transferWithId');
              }}>Not a transfer</button>`
              : null}
            ${editing && !trade && !txn.transferId && (txn.payeeRaw || txn.payee)
              ? html`<button type="button" class="btn" onClick=${() =>
                // New rule opens over this dialog, which stays as it is (S2.7.6, S12.15.7).
                openDialog(NewRuleDialog, {
                  fill: {
                    payeeMatch: txn.payeeRaw || txn.payee,
                    categoryId: t?.get('categoryId') || null,
                  },
                })}>Make a rule</button>`
              : null}<span class="spacer" style=${{ flex: 1 }}></span>
            <button type="button" class="btn" data-cancel>Cancel</button>
          `}>
      ${t
        ? html`
          <fieldset disabled=${readOnly} style=${{ border: 0, padding: 0, margin: 0 }}>
            ${!editing
              ? html`
                <${RecField} rec=${t} name="accountId" label="Account"
                  options=${writable.map((a) => [a.id, a.name])} />
              `
              : null}
            <div class="row">
              <${RecField} rec=${t} name="date" label="Date" />
              <${RecField} rec=${t} name="kind" label="Kind"
                options=${type.investing ? TRADE_KINDS : BANK_KINDS} />
            </div>
            ${trade
              ? html`
                <div class="row">
                  <${RecField} rec=${t} name="symbol" label="Symbol" placeholder="ex: VTI"
                    disabled=${editing} />
                  <${RecField} rec=${t} name="quantity" label="Quantity" />
                  <${RecField} rec=${t} name="price" label="Price" />
                </div>
              `
              : null}
            ${kind === 'sell' && type.investing && draft
              ? html`<${LotPicks} t=${t} draft=${draft} saleId=${editing ? txn.id : null} />`
              : null}
            <div class="row">
              <${RecField} rec=${t} name="amount" label="Amount" hint=${kind === 'reward'
                ? 'No cash moves: 0. The coins are income at the price, their basis that value.'
                : kind === 'foreign-tax'
                ? 'What the fund paid abroad, as money out (1099-DIV box 7).'
                : trade
                ? 'The cash effect: − for a buy, + for a sale, after fees.'
                : '− for money out, + for money in.'} />
              ${trade ? html`<${RecField} rec=${t} name="fees" label="Fees" />` : null}
            </div>
            ${kind === 'transfer-in' ? html`<${TransferLots} t=${t} />` : html`
              <${RecField} rec=${t} name="costBasis" label="Cost basis"
                hint="What the shares cost. Without it, the lot is marked basis missing until you add it." />
            `}
            ${!trade ? html`<${RecField} rec=${t} name="payee" label="Payee" />` : null}
            ${!trade && !parts.length
              ? html`<${CategoryField} rec=${t} name="categoryId" label="Category" />`
              : null}
            ${!trade
              ? html`
                <div class="field">
                  <div class="toolbar" style=${{ marginBottom: 0 }}>
                    <span class="small dim">${parts.length
                      ? 'Split across categories'
                      : ''}</span><span class="spacer"></span>
                    <button type="button" class="btn sm" onClick=${addPart}>
                      ${parts.length ? 'Add a part' : 'Split…'}</button>
                  </div>
                  ${parts.map((r, i) =>
                    html`
                      <div class="row" key=${r.key} style=${{ alignItems: 'end' }}>
                        <${Field} label=${'Part ' + (i + 1) + ' category'} help="split"
                          id=${'split-' + i + '-category'} error=${r.error('categoryId')}>
                          <${CategoryField} rec=${r} name="categoryId" bare
                            id=${'split-' + i + '-category'} help="split" label=${'Part ' +
                              (i + 1) + ' category'} />
                          </${Field}>
                          <${Field} label=${'Part ' + (i + 1) + ' amount'} help="split"
                            id=${'split-' + i + '-amount'} error=${r.error('amount')}>
                            <${RecField} rec=${r} name="amount" bare label=${'Part ' + (i + 1) +
                              ' amount'} />
                            </${Field}>
                            ${t.applies('deductible')
                              ? html`
                                <${Deductible} rec=${r} label=${'Part ' + (i + 1) + ' deductible'}
                                  id=${'split-' + i + '-deductible'} />
                              `
                              : null}
                            <button type="button" class="icon-btn" aria-label=${'Remove part ' +
                              (i + 1)} onClick=${() => draft?.remove(r)}
                              style=${{ marginBottom: '14px' }}>×</button>
                            </div>
                    `
                  )}
                  ${parts.length
                    ? html`<div class=${'small ' + (left.isZero() ? 'dim' : 'err')}>${
                      left.isZero() ? 'The parts add up.' : `${money(left)} still to place`
                    }</div>`
                    : null}
                  ${t.error('splits') ? html`<div class="err">${t.error('splits')}</div>` : null}
                </div>
              `
              : null}
            ${type.contributions && kind === 'deposit'
              ? html`
                <div class="row">
                  <${RecField} rec=${t} name="contributionYear" label="Contribution year"
                    hint="A contribution made before the April deadline may be for the year before." />
                  <${Field} label="Contributed by" id="contribution-source">
                    <${RecField} rec=${t} name="contributionSource" bare label="Contributed by"
                      options=${[
                        ['', '—'],
                        ['employee', 'Me'],
                        ['employer', 'My employer'],
                        ['rollover', 'A rollover'],
                        ['conversion', 'A Roth conversion'],
                      ]} />
                    </${Field}>
                    </div>
              `
              : null}
            ${t.applies('deductible') && !parts.length
              ? html`<${Deductible} rec=${t} label="Deductible" id="deductible" />`
              : null}
            <${RecField} rec=${t} name="memo" label="Memo" />
            ${draft
              ? html`<${TagsField} rec=${t} draft=${draft} hint="Yours only, separated by commas." />`
              : null}
            ${!type.investing && !parts.length
              ? html`
                <${SwitchRow} label="Reimbursable" hint="To be paid back; it keeps its category."
                  on=${t.get('reimbursable') != null} onChange=${(/** @type {boolean} */ on) =>
                    t.set(
                      'reimbursable',
                      on && t.get('amount') != null && Dec.of(t.get('amount')).isNegative()
                        ? Dec.of(t.get('amount')).neg()
                        : null,
                    )} />
                ${t.get('reimbursable') != null
                  ? html`
                    <div class="row">
                      <${RecField} rec=${t} name="reimbursable" label="Reimbursable amount" />
                      <${RecField} rec=${t} name="owedBy" label="Owed by"
                        placeholder="ex: Acme Corp" />
                    </div>
                  `
                  : null}
              `
              : null}
          </fieldset>
          ${editing ? html`<${InBudgets} txn=${txn} rec=${t} />` : null}
          ${editing && draft
            ? html`<${TxnReceipts} txn=${txn} draft=${draft} canWrite=${!readOnly} />`
            : null}
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * A sale's lots (S2.3): the lots held on its day, each with how many the sale takes from it;
 * typed, the sale is specific identification, and what isn't picked goes oldest first. A lot
 * a wash sale split is listed whole. A pick is a record of the sale, made once a quantity is
 * typed.
 * @param {{ t: Txn, draft: any, saleId: string | null }} p
 */
function LotPicks({ t, draft, saleId }) {
  const symbol = String(t.get('symbol') || '').trim().toUpperCase();
  const date = t.get('date');
  const accountId = t.get('accountId');
  const res = useList(
    symbol && date && accountId ? `/accounts/${accountId}/lots` : null,
    saleId ? { date, saleId } : { date },
  );
  const lots = (/** @type {any[]} */ (res.data) || []).filter((l) => l.symbol === symbol);
  const picks =
    /** @type {Pick[]} */ (draft.records.filter((/** @type {any} */ r) =>
      r instanceof Pick && r.get('saleId') === t.id
    ));
  // Each lot listed has its pick, made only once a quantity is typed (an optional record).
  useEffect(() => {
    for (const l of lots) {
      if (!picks.some((p) => p.get('lotId') === l.lotId)) {
        // Settled: an empty pick is no change of the person's, and isn't sent.
        draft.add(Pick, { saleId: t.id, lotId: l.lotId }, { optional: true }).settle();
      }
    }
  }, [lots.map((l) => l.lotId).join(), t.id]);
  // A pick read with the sale and emptied is taken away; typed again, it comes back.
  const emptied = picks.map((p) => `${p.id}:${p.get('quantity') == null}`).join();
  useEffect(() => {
    for (const p of picks) {
      if (p.state !== 'read') continue;
      const empty = p.get('quantity') == null;
      if (empty && !p.removed) draft.remove(p);
      else if (!empty && p.removed) draft.unremove(p);
    }
  }, [emptied]);
  if (!symbol || !lots.length) return null;
  const taken = picks.filter((p) => !p.removed && p.get('quantity') != null).reduce(
    (x, p) => x.add(Dec.of(p.get('quantity'))),
    Dec.parse('0'),
  );
  const sold = t.get('quantity') != null ? Dec.of(t.get('quantity')) : null;
  const refused = picks.map((p) => p.error('quantity') || p.error('lotId') || p.error(null))
    .find(Boolean);
  const over = sold != null && taken.cmp(sold) > 0;
  return html`
    <fieldset class="field" style=${{ border: 0, padding: 0, margin: '0 0 14px' }}>
      <legend class="small" style=${{ color: 'var(--fg-dim)' }}>Lots</legend>
      <table class="t">
        <thead>
          <tr>
            <th>Bought</th>
            <th class="num">Held</th>
            <th class="num">Cost</th>
            <th>Term</th>
            <th class="num">Take</th>
          </tr>
        </thead>
        <tbody>
          ${lots.map((l) => {
            const p = picks.find((x) => x.get('lotId') === l.lotId);
            return html`
              <tr key=${l.lotId}>
                <td>${l.acquiredOn}</td>
                <td class="num">${l.quantity}</td>
                <td class="num">${l.basis == null ? 'missing' : money(l.basis)}</td>
                <td>${l.longTerm ? 'long' : 'short'}</td>
                <td class="num">${p
                  ? html`
                    <${RecField} rec=${p} name="quantity" bare help="take"
                      label=${`Take from the lot bought ${l.acquiredOn}`} />
                  `
                  : null}</td>
              </tr>
            `;
          })}
        </tbody>
      </table>
      ${refused ? html`<div class="err">${refused}</div>` : null}
      <div class=${'small ' + (over ? 'err' : 'dim')}>${taken.isZero()
        ? "None picked: the account's lot method chooses."
        : `${taken.toString()} of ${sold != null ? sold.toString() : '?'} picked. ` +
          (over ? 'More than the sale.' : "What isn't picked goes oldest first.")}</div>
    </fieldset>
  `;
}

/**
 * The budgets counting a transaction, what it counts as in each, and each one's leave-out
 * (S7.3.5), kept in the transaction's draft: the category is the transaction's, the same in
 * every budget.
 * @param {{ txn: any, rec: Txn }} p
 */
function InBudgets({ txn, rec }) {
  const res = useList(`/transactions/${txn.id}/budgets`);
  const rows = /** @type {any[]} */ (res.data) || [];
  if (!rows.length) return null;
  const out = /** @type {string[]} */ (rec.get('leftOutOf') || []);
  const flip = (/** @type {any} */ r, /** @type {boolean} */ on) =>
    rec.set(
      'leftOutOf',
      on ? [...out, r.budgetId] : out.filter((x) => x !== r.budgetId),
    );
  return html`
    <fieldset class="field" style=${{ border: 0, padding: 0, margin: '0 0 14px' }}>
      <legend class="small" style=${{ color: 'var(--fg-dim)' }}>In budgets</legend>
      ${rows.map((r) => {
        const left = out.includes(r.budgetId);
        return html`
          <div
            class="list-item"><span class="grow">${r.name}<div class="small dim">${left
              ? 'left out: counts nowhere in it'
              : `counts in ${
                r.countsAs || 'nothing yet: uncategorised'
              }`}</div></span> <span class="small dim">Leave out</span>
                    <${Switch} on=${left} onChange=${(/** @type {boolean} */ on) => flip(r, on)}
                      label=${`Leave out of ${r.name}`} help="leave-out" disabled=${!r.access
                        .writable} /></div>
        `;
      })}
      <div class="hint">The category is the transaction's: changing it changes every budget that
        counts it.</div>
    </fieldset>
  `;
}

/**
 * The receipts attached to a transaction (S9.3), each opening its file, and a way to add one:
 * uploaded at once, into the inbox, and attached by the transaction's draft when it is saved.
 * @param {{ txn: any, draft: any, canWrite: boolean }} p
 */
function TxnReceipts({ txn, draft, canWrite }) {
  const res = useList(`/transactions/${txn.id}/receipts`);
  const rows = /** @type {any[]} */ (res.data) || [];
  const [names, setNames] = useState(/** @type {{ [id: string]: string }} */ ({}));
  const adding = /** @type {ReceiptLinkRec[]} */ (
    draft.records.filter((/** @type {any} */ x) => x instanceof ReceiptLinkRec && !x.removed)
  );
  const add = async (/** @type {FileList} */ files) => {
    const made = await uploadAll(files);
    setNames((was) => ({ ...was, ...Object.fromEntries(made.map((r) => [r.id, r.fileName])) }));
    for (const r of made) {
      if (rows.some((x) => x.id === r.id)) continue; // the same file, attached already
      draft.add(ReceiptLinkRec, { receiptId: r.id, kind: 'transaction', itemId: txn.id });
    }
  };
  return html`
    <div class="field" data-help="receipts" id="x-receipts">
      <div class="small" style=${{ color: 'var(--fg-dim)', marginBottom: '6px' }}>Receipts</div>
      <div class="toolbar" style=${{ flexWrap: 'wrap', margin: 0 }}>
        ${rows.map((r) =>
          html`
            <a class="pill" href=${`/ui/api/receipts/${r.id}/file`} target="_blank"
              rel="noopener">${r.payee || r.fileName}</a>
          `
        )}
        ${adding.map((x) =>
          html`
            <span class="pill info" title="Attached when you save">${names[x.get('receiptId')] ||
              'Receipt'}</span><button type="button"
              class="icon-btn" aria-label="Don't attach it"
              onClick=${() => draft.remove(x)}><${Icon} name="x" /></button>
          `
        )}
        ${canWrite
          ? html`
            <label class="btn sm" for="f-add-receipt">Add a receipt</label>
            <input id="f-add-receipt" class="sr-only" type="file" multiple accept=${ACCEPT}
              onChange=${(/** @type {any} */ e) => {
                add(e.currentTarget.files);
                e.currentTarget.value = '';
              }} />
          `
          : rows.length || adding.length
          ? null
          : html`<span class="small dim">None.</span>`}
      </div>
    </div>
  `;
}

/**
 * Shares moved in, lot by lot (S2.2, CR3-73): when each was bought, how many, and what it
 * cost. None typed, they arrive as one lot whose day bought is missing until it is.
 * @param {{ t: Txn }} p
 */
function TransferLots({ t }) {
  const rows = /** @type {any[]} */ (t.get('transferLots') || []);
  /** @param {any[]} next */
  const put = (next) => t.set('transferLots', next.length ? next : null);
  /** @param {number} i @param {string} k @param {string} v */
  const edit = (i, k, v) => put(rows.map((r, j) => (j === i ? { ...r, [k]: v || null } : r)));
  return html`
    <div class="field" id="f-transfer-lots">
      <label>Lots, as bought</label>
      ${rows.map((r, i) =>
        html`
          <div class="row">
            <${TypedInput} kind="date" value=${r.acquiredOn || ''} aria-label=${`Lot ${
              i + 1
            }: bought on`}
              onInput=${(/** @type {string} */ v) => edit(i, 'acquiredOn', v)} />
            <${TypedInput} kind="quantity" value=${r.quantity || ''} aria-label=${`Lot ${
              i + 1
            }: quantity`}
              placeholder="quantity" onInput=${(/** @type {string} */ v) =>
                edit(i, 'quantity', v)} />
            <${TypedInput} kind="money" value=${r.costBasis || ''} aria-label=${`Lot ${
              i + 1
            }: cost basis`}
              placeholder="cost basis" onInput=${(/** @type {string} */ v) =>
                edit(i, 'costBasis', v)} />
            <button type="button" class="btn sm" onClick=${() =>
              put(rows.filter((_, j) => j !== i))}>
              Remove</button>
          </div>
        `
      )}
      <div class="toolbar"><span class="small dim">${rows.length
        ? 'They add up to the shares moved in.'
        : 'None typed: one lot whose day bought is missing, its term unknown until you add it.'}</span><span
        class="spacer"></span><button type="button" class="btn sm" onClick=${() =>
          put([...rows, {
            acquiredOn: null,
            quantity: null,
            costBasis: null,
          }])}>Add a lot</button></div>
    </div>
  `;
}
