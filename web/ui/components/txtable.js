// The transaction table that the Transactions screen and an account's Transactions tab share
// (requirements S12.2.3): select rows to categorise them together, change a category in place,
// open a row to edit it.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { addCategory, categoryOptions, NEW, useCategories } from './categories.js';
import { date, price, quantity } from '../app/format.js';
import { Amt } from './amount.js';
import { Icon } from './icon.js';
import { openDialog } from './dialog.js';
import { toast } from './toast.js';
import { TransactionDialog } from '../screens/transaction-dialog.js';
import { whyRead } from '../app/draft.js';
import { RowTool } from './state.js';

export { useCategories };

/** What a transaction is called in its row: its payee, else its kind and symbol. @param {any} t */
const payeeOf = (t) => t.payee || (t.symbol ? `${t.kind} ${t.symbol}` : t.kind);

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
  const options = categoryOptions(cats.list);
  return html`
    ${sel.size
      ? html`<div class="toolbar notice" role="region" aria-label="Selected transactions">
          <b>${sel.size} selected</b>
          <label class="sr-only" for="f-categorise-as">Categorise as</label>
          <select class="in" id="f-categorise-as" style=${{ maxWidth: '260px' }} value=${bulk}
            onChange=${async (/** @type {any} */ e) => {
        const el = e.currentTarget;
        if (el.value !== NEW) return setBulk(el.value);
        const made = await addCategory();
        if (made) setBulk(made.id);
        else el.value = bulk;
      }}>
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
        <th class="num">Amount</th><th></th></tr>
          </thead>
          <tbody>${rows.map((t) =>
            html`<tr class=${sel.has(t.id) ? 'tr-sel' : ''}>
        <td><span class="tip-wrap" data-tip=${whyRead(t) || undefined}><input type="checkbox"
          aria-label=${'Select ' + (t.payee || 'transaction')} aria-description=${
              whyRead(t) ||
              undefined
            } disabled=${!t.access.writable} checked=${sel.has(t.id)} onChange=${() =>
              toggle(t.id)} /></span></td>
        <td class="dim" style=${{ whiteSpace: 'nowrap' }}>${date(t.date)}</td>
        <td><span>${payeeOf(t)}${
              t.receipts
                ? html`
                  ${' '}<span class="dim" title=${`${t.receipts} receipt${
                    t.receipts === 1 ? '' : 's'
                  }`}><${Icon} name="clip" /></span>
                `
                : null
            }</span>
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
                    onChange=${async (/** @type {any} */ e) => {
                      const el = e.currentTarget;
                      if (el.value !== NEW) return categorise([t.id], el.value);
                      const made = await addCategory();
                      if (made) categorise([t.id], made.id);
                      else el.value = t.categoryId || '';
                    }}>
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
        <td class="tool"><${RowTool} name=${payeeOf(t)} read=${!t.access.writable}
          onClick=${() =>
              openDialog(TransactionDialog, { txn: t, accounts }).then((v) =>
                v && onChanged()
              )} /></td>
      </tr>`
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}
