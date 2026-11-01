// The transaction table that the Transactions screen and an account's Transactions tab share
// (requirements S12.2.3): select rows to categorise them together, change a category in place,
// open a row to edit it.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useList } from '../app/hooks.js';
import { date, price, quantity } from '../app/format.js';
import { Amt } from './amount.js';
import { Icon } from './icon.js';
import { openDialog } from './dialog.js';
import { toast } from './toast.js';
import { TransactionDialog } from '../screens/transaction-dialog.js';

/** @returns {{ list: any[], byId: Record<string, any> }} */
export function useCategories() {
  const r = useList('/categories');
  const list = /** @type {any[]} */ (r.data) || [];
  return { list, byId: Object.fromEntries(list.map((c) => [c.id, c])) };
}

/**
 * @param {{ rows: any[], showAccount?: boolean, onChanged: () => void, accounts?: any[] }} p
 */
export function TxTable({ rows, showAccount = true, onChanged, accounts = [] }) {
  const cats = useCategories();
  const [sel, setSel] = useState(/** @type {Set<string>} */ (new Set()));
  const [bulk, setBulk] = useState('');
  const writable = rows.filter((t) => t.access.writable);
  const all = writable.length > 0 && writable.every((t) => sel.has(t.id));
  const toggle = (/** @type {string} */ id) => {
    const next = new Set(sel);
    next.has(id) ? next.delete(id) : next.add(id);
    setSel(next);
  };
  const categorise = async (/** @type {string[]} */ ids, /** @type {string} */ categoryId) => {
    const r = await api.post('/transactions/categorise', { ids, categoryId: categoryId || null });
    toast(`${r.changed} transaction${r.changed === 1 ? '' : 's'} categorised`);
    setSel(new Set());
    onChanged();
  };
  const options = [['', 'Uncategorised'], ...cats.list.map((c) => [c.id, c.path])];
  return html`
    ${sel.size
      ? html`<div class="toolbar notice" role="region" aria-label="Selected transactions">
          <b>${sel.size} selected</b>
          <label class="sr-only" for="f-categorise-as">Categorise as</label>
          <select class="in" id="f-categorise-as" style=${{ maxWidth: '260px' }} value=${bulk}
            onChange=${(/** @type {any} */ e) => setBulk(e.currentTarget.value)}>
            ${options.map(([v, l]) => html`<option value=${v}>${l}</option>`)}</select>
          <button type="button" class="btn sm primary" onClick=${() =>
        categorise([...sel], bulk)}>Categorise</button>
          <button type="button" class="btn sm" onClick=${() =>
        setSel(new Set())}>Clear</button></div>`
      : null}
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only">Transactions</caption>
          <thead>
            <tr>
        <th><input type="checkbox" aria-label="Select all" checked=${all} disabled=${!writable
          .length}
          onChange=${() => setSel(all ? new Set() : new Set(writable.map((t) => t.id)))} /></th>
        <th>Date</th><th>Payee</th><th>Category</th>${showAccount ? html`<th>Account</th>` : null}
        <th class="num">Amount</th></tr>
          </thead>
          <tbody>${rows.map((t) =>
            html`<tr class=${sel.has(t.id) ? 'tr-sel' : ''}>
        <td><input type="checkbox" aria-label=${'Select ' + (t.payee || 'transaction')}
          disabled=${!t.access.writable} checked=${sel.has(t.id)} onChange=${() =>
              toggle(t.id)} /></td>
        <td class="dim" style=${{ whiteSpace: 'nowrap' }}>${date(t.date)}</td>
        <td><button type="button" class="linklike" style=${{
              color: 'var(--fg)',
              textAlign: 'left',
            }}
            onClick=${() =>
              openDialog(TransactionDialog, { txn: t, accounts }).then((v) => v && onChanged())}>
            ${t.payee || (t.symbol ? `${t.kind} ${t.symbol}` : t.kind)}${
              t.receipts
                ? html`
                  <span class="dim" title=${`${t.receipts} receipt${
                    t.receipts === 1 ? '' : 's'
                  }`}><${Icon} name="clip" /></span>
                `
                : null
            }</button>
          ${
              t.symbol && t.quantity
                ? html`<div class="small dim">${quantity(t.quantity)} ${t.symbol}${
                  t.price ? [' at ', html`<span class="amt">${price(t.price)}</span>`] : null
                }</div>`
                : null
            }
          ${
              t.transferId
                ? html`<div class="small dim"><${Icon} name="tx" /> transfer${
                  t.transferAccountName ? ' with ' + t.transferAccountName : ''
                }</div>`
                : null
            }
          ${
              t.tags.length
                ? html`<div class="small">${
                  t.tags.map((/** @type {string} */ g) =>
                    html`
                      <span class="pill">${g}</span>
                    `
                  )
                }</div>`
                : null
            }
          ${
              t.amountWas
                ? html`<div class="small" style=${{
                  color: 'var(--ask)',
                }}>amount changed in a later import</div>`
                : null
            }${
              t.offChainAt
                ? html`<div class="small"><span class="pill warn">no longer on the chain</span>
                    <button type="button" class="btn sm" onClick=${(/** @type {Event} */ e) => {
                  e.stopPropagation();
                  api.post(`/transactions/${t.id}/keep`, undefined, { version: t.version }).then(
                    () => {
                      toast('Kept');
                      onChanged && onChanged();
                    },
                  ).catch((/** @type {any} */ x) => toast(x.message));
                }}>Keep it</button></div>`
                : null
            }</td>
        <td>${
              t.splits.length
                ? html`<span class="pill">Split ${t.splits.length} ways</span>`
                : t.transferId || t.symbol
                ? html`<span class="dim small">—</span>`
                : !t.access.writable
                ? (t.categoryId
                  ? html`<span class="pill">${cats.byId[t.categoryId]?.path}</span>`
                  : html`<span class="pill warn">Uncategorised</span>`)
                : html`
                  <select class="in" style=${{ height: '30px', maxWidth: '220px' }}
                    aria-label=${'Category of ' +
                      (t.payee || 'transaction')} value=${t.categoryId || ''}
                    onChange=${(/** @type {any} */ e) => categorise([t.id], e.currentTarget.value)}>
                                ${options.map(([v, l]) =>
                                  html`<option value=${v}>${l}</option>`
                                )}</select>
                `
            }</td>
        ${showAccount ? html`<td class="small dim">${t.accountName}</td>` : null}
        <td class="num"><${Amt} v=${t.amount} signed />${
              t.reconciled
                ? html`<div class="small dim"><${Icon} name="lock" /> reconciled</div>`
                : t.cleared
                ? html`<div class="small dim"><${Icon} name="check" /> cleared</div>`
                : null
            }</td>
      </tr>`
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}
