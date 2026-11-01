// Recording an option trade (requirements S3.2): buy or sell, to open or to close, a contract
// by its underlying, call or put, strike and expiry.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { Record } from '../app/draft.js';
import { DraftDialog, RecField, useDraft } from './draft-form.js';
import { FIELDS } from '../api/fields.js';
import { api } from '../api/client.js';
import { useList, useSubmit } from '../app/hooks.js';
import { money, today } from '../app/format.js';
import { Dialog } from './dialog.js';
import { useDialogGuide } from './help.js';
import { errAt, Field, FormError, Input, Seg } from './fields.js';
import { toast } from './toast.js';
import { dec } from '../app/dec.js';

export const ACTIONS = /** @type {[string, string][]} */ ([
  ['buy-to-open', 'Buy to open'],
  ['sell-to-open', 'Sell to open'],
  ['buy-to-close', 'Buy to close'],
  ['sell-to-close', 'Sell to close'],
]);
const clean = (/** @type {string} */ s) => (s ? String(s).replace(/[$,\s]/g, '') : '');

/**
 * An option trade as its dialog's draft makes it (S3.2): a transaction of the trade's kind,
 * `symbol` the underlying, `quantity` the contracts and `price` the premium a share, with the
 * contract's right, strike and expiry; its amount the cash the trade comes to.
 */
class OptionTxn extends Record {
  /** @override */
  static prefix = 'Txn';
  /** @override */
  static fields = FIELDS.TxnRecord;
  /** @override */
  static defaults = { payee: null, memo: null, multiplier: null };
}

/** What a trade does to the account's cash: paid out to buy, received to sell, less fees. */
function cashOf(/** @type {OptionTxn} */ r) {
  try {
    const gross = dec(r.get('quantity') || 0).mul(dec(r.get('price') || 0)).mul(100).round(2);
    const fees = dec(r.get('fees') || 0);
    return String(r.get('kind').startsWith('buy') ? gross.neg().sub(fees) : gross.sub(fees));
  } catch {
    return null;
  }
}

/** @param {{ close: (v?: any) => void, accountId?: string, start?: any }} p */
export function OptionTrade({ close, accountId, start }) {
  useDialogGuide('dialog-option-trade');
  const accounts = useList('/accounts');
  const list = (/** @type {any[]} */ (accounts.data) || []).filter((a) =>
    a.investing && a.active && a.access.writable
  );
  // The account given, or the first the list offers, until another is chosen.
  const f = useDraft(async (draft) => {
    const first = accountId || (/** @type {any[]} */ ((await api.get('/accounts')).items))
      .find((a) => a.investing && a.active && a.access.writable)?.id;
    draft.add(OptionTxn, {
      accountId: first || null,
      date: today(),
      kind: start?.action || 'sell-to-open',
      symbol: start?.underlying || '',
      right: start?.right || 'put',
      strike: start?.strike || null,
      expiry: start?.expiry || null,
      quantity: start?.contracts || '1',
      price: null,
      fees: '0.65',
    });
  }, [accountId]);
  const rec = /** @type {OptionTxn | undefined} */ (f.draft?.records[0]);
  const cash = rec ? cashOf(rec) : null;
  const before = () => {
    if (!rec || cash === null) return false;
    rec.set('amount', cash);
  };
  return html`
    <${DraftDialog} f=${f} title="Record an option trade" close=${close} what="This trade"
      label="Record" done="Option trade recorded" before=${before}
      disabled=${!rec?.get('accountId')}>
      ${rec
        ? html`
          <div class="field" data-help="action" id="x-action"><label>Trade</label>
            <${Seg} label="Trade" value=${rec.get('kind')} onChange=${(/** @type {string} */ v) =>
              rec.set('kind', v)} options=${ACTIONS} /></div>
          <div class="row">
            <${RecField} rec=${rec} name="accountId" label="Account" id="account"
              options=${list.map((a) => [a.id, a.name])} />
            <${RecField} rec=${rec} name="date" label="Date" type="date" />
          </div>
          <div class="row">
            <${RecField} rec=${rec} name="symbol" label="Underlying" placeholder="MSFT" />
            <${RecField} rec=${rec} name="right" label="Call or put" id="right"
              options=${[['call', 'Call'], ['put', 'Put']]} />
            <${RecField} rec=${rec} name="strike" label="Strike" placeholder="480" />
            <${RecField} rec=${rec} name="expiry" label="Expiry" type="date" />
          </div>
          <div class="row">
            <${RecField} rec=${rec} name="quantity" label="Contracts" hint="100 shares each." />
            <${RecField} rec=${rec} name="price" label="Premium" hint="A share, as quoted." />
            <${RecField} rec=${rec} name="fees" label="Fees and commission" id="fees" />
          </div>
          <p class="small dim">${cash !== null && !dec(rec.get('price') || 0).isZero()
            ? `${dec(cash).isNegative() ? 'Paid' : 'Received'}: ${money(String(dec(cash).abs()))}.`
            : ''} ${rec.get('kind') === 'sell-to-open'
            ? 'A short option is a negative lot: the credit is its basis, realized at close or expiry.'
            : ''}</p>
        `
        : null}
    </${DraftDialog}>
  `;
}

/** An option's end: expired, assigned (short) or exercised (long) (S3.4, S3.6). */
/** @param {{ close: (v?: any) => void, row: any }} p */
export function Settle({ close, row }) {
  useDialogGuide('dialog-option-settle');
  const short = row.side === 'short';
  const [f, setF] = useState({
    how: row.inTheMoney === false ? 'expired' : short ? 'assign' : 'exercise',
    date: row.expiry || today(),
    contracts: String(dec(row.quantity).abs()).replace(/\.0+$/, ''),
  });
  const set = (/** @type {string} */ k) => (/** @type {any} */ x) => setF({ ...f, [k]: x });
  const save = useSubmit(async () => {
    await api.post(`/accounts/${row.accountId}/options/${row.instrumentId}/settle`, {
      how: f.how,
      date: f.date,
      contracts: clean(f.contracts),
    });
    toast(`${row.symbol}: recorded`);
    close(true);
  });
  const e = save.error;
  return html`
    <${Dialog} title=${`${row.symbol}: what happened?`} close=${close} onSubmit=${() =>
      save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Record</button>`}>
      <div class="field" data-help="how" id="x-how"><label>It was</label>
        <${Seg} label="It was" value=${f.how} onChange=${set('how')} options=${[
          ['expired', 'Expired worthless'],
          short ? ['assign', 'Assigned'] : ['exercise', 'Exercised'],
        ]} /></div>
      <div class="row">
        <${Field} label="On" id="settle-date" error=${errAt(e, 'date')}>
          <${Input} type="date"
            value=${f.date} onInput=${set('date')} />
          </${Field}>
          <${Field} label="Contracts" id="settle-contracts" error=${errAt(e, 'contracts')}>
            <${Input}
              value=${f.contracts} onInput=${set('contracts')} inputmode="numeric" />
            </${Field}>
            </div>
            <p class="small dim">${f.how === 'expired'
              ? short ? 'The credit is kept as a gain.' : 'The premium paid is lost.'
              : 'The shares are bought or sold at the strike, with the premium folded into their basis or proceeds.'}</p>
            <${FormError} error=${e} />
            </${Dialog}>
  `;
}

/** A typed mark for an option the source doesn't price (S3.7, S4.5). */
/** @param {{ close: (v?: any) => void, row: any }} p */
export function Mark({ close, row }) {
  useDialogGuide('dialog-option-mark');
  // A price typed for a day is changed; a day without one gets one (S4.10).
  const [day, setDay] = useState(today());
  const f = useDraft(async (draft) => {
    const closes = await api.get(`/instruments/${row.instrumentId}/prices`, {
      from: day,
      to: day,
    });
    const mine = closes.items.find((/** @type {any} */ c) => c.id && c.date === day);
    if (mine) draft.load(TypedPriceRec, { ...mine, instrumentId: row.instrumentId });
    else draft.add(TypedPriceRec, { instrumentId: row.instrumentId, date: day });
  }, [row.instrumentId, day]);
  const rec = f.draft?.records[0];
  return html`
    <${DraftDialog} f=${f} title=${`Mark ${row.symbol}`} close=${close} what="This mark"
      done=${`${row.symbol}: marked`}>
      <div class="row">
        <${Field} label="On" id="mark-date" error=${rec?.error('date')}>
          <${Input} type="date" value=${day} onInput=${setDay} />
        </${Field}>
        ${rec
          ? html`
            <${RecField} rec=${rec} name="close" label="Mark" id="mark-price"
              hint="A share, as quoted." />
          `
          : null}
      </div>
      <p class="small dim">Used until the price source has a close for it. Without either, an
        option is marked at its intrinsic value.</p>
    </${DraftDialog}>
  `;
}

/** A price its typer typed for a day (S4.10). */
class TypedPriceRec extends Record {
  /** @override */
  static prefix = 'TyPrc';
  /** @override */
  static fields = FIELDS.TypedPriceRecord;
}
