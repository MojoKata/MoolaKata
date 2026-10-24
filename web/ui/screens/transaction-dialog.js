// Adding or editing a transaction (requirements S2.6): payee, category, memo, tags and splits;
// for an investing account, trades with their instrument, quantity, price and fees; for a
// retirement account, the contribution year and who contributed.
import { useState } from 'preact/hooks';
import { useList } from '../app/hooks.js';
import { ACCEPT, uploadAll } from '../components/receipt.js';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useSubmit } from '../app/hooks.js';
import { Dialog } from '../components/dialog.js';
import { useDialogGuide } from '../components/help.js';
import { openRules } from '../components/rules.js';
import { errAt, Field, FormError, Input, Select, SwitchRow } from '../components/fields.js';
import { toast } from '../components/toast.js';
import { cents, fromCents, money, today } from '../app/format.js';
import { useCategories } from '../components/txtable.js';
import { BY_TYPE } from '../account-types/index.js';

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
  ['deposit', 'Cash in'],
  ['withdrawal', 'Cash out'],
  ['fee', 'Fee'],
]);
const TRADE = ['buy', 'sell', 'reinvest', 'transfer-in', 'transfer-out'];

/** @param {string} s */
const clean = (s) => String(s).replace(/[$,\s]/g, '').replace('−', '-');

/**
 * `start` fills a new transaction, such as a trade a statement shows but doesn't read
 * (S1.3.3.8).
 * @param {{ close: (v?: any) => void, txn?: any, start?: any, accounts: any[],
 *   accountId?: string }} p
 */
export function TransactionDialog({ close, txn, start, accounts, accountId }) {
  useDialogGuide('dialog-transaction');
  const editing = !!txn;
  const readOnly = editing && txn.level === 'read';
  const writable = accounts.filter((a) => a.level !== 'read');
  const [acct, setAcct] = useState(txn?.accountId || accountId || writable[0]?.id || '');
  const account = accounts.find((a) => a.id === acct) || { type: 'checking' };
  const type = BY_TYPE[account.type] || BY_TYPE.checking;
  const cats = useCategories();
  const init = txn || start;
  const [f, setF] = useState({
    date: init?.date || today(),
    kind: init?.kind || (type.investing ? 'buy' : 'withdrawal'),
    amount: init?.amount || '',
    payee: init?.payee || '',
    memo: init?.memo || '',
    categoryId: init?.categoryId || '',
    symbol: init?.symbol || '',
    quantity: init?.quantity || '',
    price: init?.price || '',
    fees: init?.fees || '',
    costBasis: '',
    contributionYear: init?.contributionYear ? String(txn.contributionYear) : '',
    contributionSource: init?.contributionSource || '',
    tags: (init?.tags || []).join(', '),
    reimbursable: txn?.reimbursable || '',
    owedBy: txn?.owedBy || '',
  });
  const [owed, setOwed] = useState(!!txn?.reimbursable);
  const [splits, setSplits] = useState(
    /** @type {{ categoryId: string, amount: string, memo: string, reimbursable?: string,
     *   owedBy?: string }[]} */ (
      (txn?.splits || []).map((/** @type {any} */ s) => ({
        categoryId: s.categoryId || '',
        amount: s.amount,
        memo: s.memo || '',
        reimbursable: s.reimbursable || undefined,
        owedBy: s.owedBy || undefined,
      }))
    ),
  );
  const set = (/** @type {string} */ k) => (/** @type {string} */ v) => setF({ ...f, [k]: v });
  const changeAccount = (/** @type {string} */ id) => {
    setAcct(id);
    // A kind the new account's type doesn't have goes back to its first.
    const next = BY_TYPE[accounts.find((a) => a.id === id)?.type] || BY_TYPE.checking;
    const kinds = next.investing ? TRADE_KINDS : BANK_KINDS;
    if (!kinds.some(([k]) => k === f.kind)) setF({ ...f, kind: kinds[0][0] });
  };
  const trade = TRADE.includes(f.kind);
  const body = () => {
    /** @type {Record<string, any>} */
    const b = {
      date: f.date,
      kind: f.kind,
      amount: clean(f.amount),
      payee: f.payee || null,
      memo: f.memo || null,
      categoryId: splits.length ? null : f.categoryId || null,
      splits: splits.map((s) => ({
        categoryId: s.categoryId || null,
        amount: clean(s.amount),
        memo: s.memo || null,
        // A part marked to be paid back keeps its mark (S2.9).
        ...(s.reimbursable ? { reimbursable: s.reimbursable, owedBy: s.owedBy || null } : {}),
      })),
      // Spending to be paid back: all of it unless a smaller amount is typed (S2.9).
      reimbursable: owed && !splits.length
        ? clean(f.reimbursable) || clean(f.amount).replace(/^-/, '') || null
        : null,
      owedBy: owed && !splits.length ? f.owedBy || null : null,
      tags: f.tags.split(',').map((x) => x.trim()).filter(Boolean),
    };
    if (type.investing) {
      b.quantity = f.quantity ? clean(f.quantity) : null;
      b.price = f.price ? clean(f.price) : null;
      b.fees = f.fees ? clean(f.fees) : null;
      if (!editing) b.symbol = f.symbol || null;
      if (f.kind === 'transfer-in') b.costBasis = f.costBasis ? clean(f.costBasis) : null;
    }
    if (type.contributions) {
      b.contributionYear = f.contributionYear ? Number(f.contributionYear) : null;
      b.contributionSource = f.contributionSource || null;
    }
    return b;
  };
  const save = useSubmit(async (/** @type {boolean} */ confirm = false) => {
    if (editing) {
      await api.patch(
        `/transactions/${txn.id}`,
        body(),
        txn.version,
        confirm ? { confirm: true } : undefined,
      );
      toast('Saved');
    } else {
      await api.post('/transactions', { accountId: acct, ...body() }, {
        idempotent: true,
        ...(confirm ? { params: { confirm: true } } : {}),
      });
      toast('Added');
    }
    close(true);
  });
  const remove = useSubmit(async (/** @type {boolean} */ confirm = false) => {
    await api.del(`/transactions/${txn.id}`, txn.version, confirm ? { confirm: true } : undefined);
    toast('Deleted');
    close(true);
  });
  const unlink = useSubmit(async () => {
    await api.post(`/transactions/${txn.id}/transfer`, { otherId: null });
    toast('No longer a transfer');
    close(true);
  });
  const e = save.error;
  // A reconciled period, or a year whose return is filed (S2.8): asked, then done anyway.
  const reconciled = ['reconciled-period', 'closed-year'].includes(e?.code);
  const removeAsk = ['reconciled-period', 'closed-year'].includes(remove.error?.code);
  const options = [['', 'Uncategorised'], ...cats.list.map((c) => [c.id, c.path])];
  const splitTotal = splits.reduce((s, x) => s + (cents(x.amount) ?? 0n), 0n);
  const left = (cents(f.amount) ?? 0n) - splitTotal;
  const [armed, setArmed] = useState(false);

  return html`
    <${Dialog} title=${readOnly ? 'Transaction' : editing ? 'Edit transaction' : 'Add transaction'}
      close=${close} onSubmit=${() => !readOnly && save.run(reconciled).catch(() => {})}
      footer=${readOnly
        ? html`<button type="button" class="btn" onClick=${() => close()}>Close</button>`
        : html`
          ${editing
            ? html`
              <button type="button" class="btn danger" disabled=${remove.busy}
                onClick=${() =>
                  armed ? remove.run(removeAsk).catch(() => {}) : setArmed(true)}>${removeAsk
                  ? 'Delete it anyway'
                  : armed
                  ? (['assign', 'exercise'].includes(txn.kind)
                    ? 'Click again to delete it and its stock trade'
                    : 'Click again to delete')
                  : 'Delete'}</button>
            `
            : null}
          ${editing && txn.transferId
            ? html`<button type="button" class="btn" onClick=${() =>
              unlink.run()}>Not a transfer</button>`
            : null}
          ${editing && !trade && !txn.transferId && (txn.payeeRaw || txn.payee)
            ? html`<button type="button" class="btn" onClick=${() => {
              // One dialog at a time: this one closes, and the rule opens filled from it.
              close();
              setTimeout(() =>
                openRules({
                  payeeMatch: txn.payeeRaw || txn.payee,
                  categoryId: f.categoryId || null,
                }), 0);
            }}>Make a rule</button>`
            : null}
          <span class="spacer" style=${{ flex: 1 }}></span>
          <button type="button" class="btn" onClick=${() => close()}>Cancel</button>
          <button class="btn primary" disabled=${save.busy}>${reconciled
            ? 'Change it anyway'
            : editing
            ? 'Save'
            : 'Add'}</button>
        `}>
      <fieldset disabled=${readOnly} style=${{ border: 0, padding: 0, margin: 0 }}>
        ${!editing
          ? html`
            <${Field} label="Account">
              <${Select} value=${acct} onChange=${changeAccount}
                options=${writable.map((a) => [a.id, a.name])} />
              </${Field}>
          `
          : null}
        <div class="row">
          <${Field} label="Date" error=${errAt(e, 'date')}><${Input} type="date" value=${f.date}
            onInput=${set('date')} required /></${Field}>
          <${Field} label="Kind" error=${errAt(e, 'kind')}><${Select} value=${f
            .kind} onChange=${set('kind')}
            options=${type.investing ? TRADE_KINDS : BANK_KINDS} /></${Field}>
        </div>
        ${trade
          ? html`
            <div class="row">
              <${Field} label="Symbol" error=${errAt(e, 'symbol')}>
                <${Input} value=${f.symbol}
                  onInput=${set('symbol')} placeholder="VTI" disabled=${editing} />
                </${Field}>
                <${Field} label="Quantity" error=${errAt(e, 'quantity')}>
                  <${Input} value=${f.quantity}
                    onInput=${set('quantity')} inputmode="decimal" />
                  </${Field}>
                  <${Field} label="Price" error=${errAt(e, 'price')}>
                    <${Input} value=${f.price}
                      onInput=${set('price')} inputmode="decimal" />
                    </${Field}>
                    </div>
          `
          : null}
        <div class="row">
          <${Field} label="Amount" error=${errAt(e, 'amount')} hint=${trade
            ? 'The cash effect: − for a buy, + for a sale, after fees.'
            : '− for money out, + for money in.'}><${Input} value=${f.amount} onInput=${set(
              'amount',
            )}
            inputmode="decimal" required /></${Field}>
          ${trade
            ? html`
              <${Field} label="Fees" error=${errAt(e, 'fees')}>
                <${Input} value=${f.fees}
                  onInput=${set('fees')} inputmode="decimal" />
                </${Field}>
            `
            : null}
        </div>
        ${f.kind === 'transfer-in'
          ? html`
            <${Field} label="Cost basis" error=${errAt(e, 'costBasis')}
              hint="What the shares cost. Without it, the lot is marked basis missing until you add it.">
              <${Input}
                value=${f.costBasis} onInput=${set('costBasis')} inputmode="decimal" />
              </${Field}>
          `
          : null}
        ${!trade
          ? html`
            <${Field} label="Payee" error=${errAt(e, 'payee')}>
              <${Input} value=${f.payee}
                onInput=${set('payee')} />
              </${Field}>
          `
          : null}
        ${!trade && !splits.length
          ? html`
            <${Field} label="Category" error=${errAt(e, 'categoryId')}>
              <${Select}
                value=${f.categoryId} onChange=${set('categoryId')} options=${options} />
              </${Field}>
          `
          : null}
        ${!trade
          ? html`<div class="field"><div class="toolbar" style=${{ marginBottom: 0 }}>
        <span class="small dim">${
            splits.length ? 'Split across categories' : ''
          }</span><span class="spacer"></span>
        <button type="button" class="btn sm" onClick=${() =>
            setSplits([...splits, { categoryId: '', amount: '', memo: '' }])}>
          ${splits.length ? 'Add a part' : 'Split…'}</button></div>
      ${
            splits.map((s, i) =>
              html`
                <div class="row" style=${{ alignItems: 'end' }}>
                  <${Field} label=${'Part ' + (i + 1) + ' category'} help="split" id=${'split-' +
                    i +
                    '-category'}
                    error=${errAt(e, `splits.${i}.categoryId`)}>
                    <${Select} value=${s.categoryId} options=${options}
                      onChange=${(/** @type {string} */ v) =>
                        setSplits(splits.map((x, j) => (j === i ? { ...x, categoryId: v } : x)))} />
                    </${Field}>
                    <${Field} label=${'Part ' + (i + 1) + ' amount'} help="split" id=${'split-' +
                      i + '-amount'}>
                      <${Input}
                        value=${s.amount} inputmode="decimal" onInput=${(/** @type {string} */ v) =>
                          setSplits(splits.map((x, j) => (j === i ? { ...x, amount: v } : x)))} />
                      </${Field}>
                      <button type="button" class="icon-btn" aria-label=${'Remove part ' + (i + 1)}
                        onClick=${() => setSplits(splits.filter((_, j) => j !== i))} style=${{
                          marginBottom: '14px',
                        }}>×</button>
                      </div>
              `
            )
          }
      ${
            splits.length
              ? html`<div class=${'small ' + (left ? 'err' : 'dim')}>${
                left ? `${money(fromCents(left))} still to place` : 'The parts add up.'
              }</div>`
              : null
          }
      ${errAt(e, 'splits') ? html`<div class="err">${errAt(e, 'splits')}</div>` : null}
    </div>`
          : null}
        ${type.contributions && ['deposit'].includes(f.kind)
          ? html`
            <div class="row">
              <${Field} label="Contribution year" error=${errAt(e, 'contributionYear')}
                hint="A contribution made before the April deadline may be for the year before.">
                <${Input}
                  value=${f.contributionYear} onInput=${set(
                    'contributionYear',
                  )} inputmode="numeric" />
                </${Field}>
                <${Field} label="Contributed by" id="contribution-source">
                  <${Select} value=${f.contributionSource}
                    onChange=${set('contributionSource')} options=${[
                      ['', '—'],
                      ['employee', 'Me'],
                      ['employer', 'My employer'],
                      ['rollover', 'A rollover'],
                    ]} />
                  </${Field}>
                  </div>
          `
          : null}
        <${Field} label="Memo"><${Input} value=${f.memo} onInput=${set('memo')} /></${Field}>
        <${Field} label="Tags" hint="Yours only, separated by commas."><${Input} value=${f.tags}
          onInput=${set('tags')} /></${Field}>
        ${!type.investing && !splits.length
          ? html`
            <${SwitchRow} label="Reimbursable" hint="To be paid back; it keeps its category."
              on=${owed} onChange=${setOwed} />
            ${owed
              ? html`
                <div class="row">
                  <${Field} label="Reimbursable amount" error=${errAt(e, 'reimbursable')}>
                    <${Input} value=${f.reimbursable} onInput=${set('reimbursable')}
                      inputmode="decimal" placeholder="all of it" />
                    </${Field}>
                    <${Field} label="Owed by" error=${errAt(e, 'owedBy')}>
                      <${Input} value=${f.owedBy} onInput=${set('owedBy')}
                        placeholder="Acme Corp" />
                      </${Field}>
                      </div>
              `
              : null}
          `
          : null}
        </fieldset>
        ${editing ? html`<${TxnReceipts} txn=${txn} canWrite=${!readOnly} />` : null}
        ${reconciled
          ? html`<div class="notice warn" role="alert">${e.message}</div>`
          : html`<${FormError} error=${e || remove.error} shown=${[
            'date',
            'kind',
            'amount',
            'payee',
            'categoryId',
            'symbol',
            'quantity',
            'price',
            'fees',
            'costBasis',
            'contributionYear',
            'splits',
            'reimbursable',
            'owedBy',
          ]} />`}
      </${Dialog}>
  `;
}

/**
 * The receipts attached to a transaction (S9.3), each opening its file, and a way to add one.
 * @param {{ txn: any, canWrite: boolean }} p
 */
function TxnReceipts({ txn, canWrite }) {
  const res = useList(`/transactions/${txn.id}/receipts`);
  const rows = /** @type {any[]} */ (res.data) || [];
  const add = async (/** @type {FileList} */ files) => {
    for (const r of await uploadAll(files)) {
      try {
        await api.post(`/receipts/${r.id}/links`, { transactionId: txn.id });
      } catch (e) {
        toast(/** @type {any} */ (e).message);
      }
    }
    res.reload();
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
        ${canWrite
          ? html`
            <label class="btn sm" for="f-add-receipt">Add a receipt</label>
            <input id="f-add-receipt" class="sr-only" type="file" multiple accept=${ACCEPT}
              onChange=${(/** @type {any} */ e) => {
                add(e.currentTarget.files);
                e.currentTarget.value = '';
              }} />
          `
          : rows.length
          ? null
          : html`<span class="small dim">None.</span>`}
      </div>
    </div>
  `;
}
