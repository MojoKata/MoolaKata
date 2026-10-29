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
import { errAt, Field, FormError, Input, Seg, Select } from './fields.js';
import { toast } from './toast.js';
import { dec } from '../app/dec.js';

export const ACTIONS = /** @type {[string, string][]} */ ([
  ['buy-to-open', 'Buy to open'],
  ['sell-to-open', 'Sell to open'],
  ['buy-to-close', 'Buy to close'],
  ['sell-to-close', 'Sell to close'],
]);
const clean = (/** @type {string} */ s) => (s ? String(s).replace(/[$,\s]/g, '') : '');

/** @param {{ close: (v?: any) => void, accountId?: string, start?: any }} p */
export function OptionTrade({ close, accountId, start }) {
  useDialogGuide('dialog-option-trade');
  const accounts = useList('/accounts');
  const list = (/** @type {any[]} */ (accounts.data) || []).filter((a) =>
    a.investing && a.active && ['owner', 'write'].includes(a.level)
  );
  const [f, setF] = useState({
    accountId: accountId || '',
    date: today(),
    action: start?.action || 'sell-to-open',
    underlying: start?.underlying || '',
    right: start?.right || 'put',
    strike: start?.strike || '',
    expiry: start?.expiry || '',
    contracts: start?.contracts || '1',
    premium: '',
    fees: '0.65',
  });
  const set = (/** @type {string} */ k) => (/** @type {any} */ x) => setF({ ...f, [k]: x });
  const account = f.accountId || list[0]?.id || '';
  const gross = Number(clean(f.contracts)) * Number(clean(f.premium)) * 100;
  const cash = f.action.startsWith('buy')
    ? -gross - Number(clean(f.fees) || 0)
    : gross - Number(clean(f.fees) || 0);
  const save = useSubmit(async (/** @type {boolean} */ confirm = false) => {
    const out = await api.post(`/accounts/${account}/options`, {
      date: f.date,
      action: f.action,
      underlying: f.underlying,
      right: f.right,
      strike: clean(f.strike),
      expiry: f.expiry,
      contracts: clean(f.contracts),
      premium: clean(f.premium),
      fees: clean(f.fees) || '0',
    }, { idempotent: true, ...(confirm ? { params: { confirm: true } } : {}) });
    toast(`${out.payee} recorded`);
    close(out);
  });
  const e = save.error;
  const ask = e?.code === 'closed-year'; // a year whose return is filed (S2.8)
  return html`
    <${Dialog} title="Record an option trade" close=${close} onSubmit=${() =>
      save.run(ask).catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy || !account}>${
        ask ? 'Record it anyway' : 'Record'
      }</button>`}>
      <div class="field" data-help="action" id="x-action"><label>Trade</label>
        <${Seg} label="Trade" value=${f.action} onChange=${set(
          'action',
        )} options=${ACTIONS} /></div>
      <div class="row">
        <${Field} label="Account" id="account" error=${errAt(e, 'accountId')}>
          <${Select}
            value=${account} onChange=${set('accountId')} options=${list.map((
              a,
            ) => [a.id, a.name])} />
          </${Field}>
          <${Field} label="Date" error=${errAt(e, 'date')}>
            <${Input} type="date" value=${f.date}
              onInput=${set('date')} />
            </${Field}>
            </div>
            <div class="row">
              <${Field} label="Underlying" error=${errAt(e, 'underlying')}>
                <${Input} value=${f.underlying}
                  onInput=${set('underlying')} placeholder="MSFT" required />
                </${Field}>
                <${Field} label="Call or put" id="right" error=${errAt(e, 'right')}>
                  <${Select} value=${f.right}
                    onChange=${set('right')} options=${[['call', 'Call'], ['put', 'Put']]} />
                  </${Field}>
                  <${Field} label="Strike" error=${errAt(e, 'strike')}>
                    <${Input} value=${f.strike}
                      onInput=${set('strike')} inputmode="decimal" placeholder="480" required />
                    </${Field}>
                    <${Field} label="Expiry" error=${errAt(e, 'expiry')}>
                      <${Input} type="date" value=${f.expiry}
                        onInput=${set('expiry')} required />
                      </${Field}>
                      </div>
                      <div class="row">
                        <${Field} label="Contracts" error=${errAt(
                          e,
                          'contracts',
                        )} hint="100 shares each.">
                          <${Input} value=${f.contracts} onInput=${set(
                            'contracts',
                          )} inputmode="numeric" />
                          </${Field}>
                          <${Field} label="Premium" error=${errAt(
                            e,
                            'premium',
                          )} hint="A share, as quoted.">
                            <${Input} value=${f.premium} onInput=${set(
                              'premium',
                            )} inputmode="decimal"
                              required />
                            </${Field}>
                            <${Field} label="Fees and commission" id="fees" error=${errAt(
                              e,
                              'fees',
                            )}>
                              <${Input}
                                value=${f.fees} onInput=${set('fees')} inputmode="decimal" />
                              </${Field}>
                              </div>
                              <p class="small dim">${Number.isFinite(cash) && gross
                                ? `${cash < 0 ? 'Paid' : 'Received'}: ${
                                  money(String(Math.abs(cash)))
                                }.`
                                : ''} ${f.action === 'sell-to-open'
                                ? 'A short option is a negative lot: the credit is its basis, realized at close or expiry.'
                                : ''}</p>
                              <${FormError} error=${e} />
                              </${Dialog}>
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
