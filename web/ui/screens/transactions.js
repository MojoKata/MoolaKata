// Transactions (requirements S12.2.3): every account's transactions together, filtered by
// account, category, date, amount, payee and tag, with bulk categorise and Import.
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { canAdd } from '../app/draft.js';
import { api } from '../api/client.js';
import { useApi, useList } from '../app/hooks.js';
import { changes } from '../app/stream.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';
import { Empty, Failed, Loading } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { openDialog } from '../components/dialog.js';
import { offsetOf, Pager } from '../components/pager.js';
import { TxTable, useCategories } from '../components/txtable.js';
import { pageSize } from '../store/prefs.js';
import { ImportDialog } from './import.js';
import { openRules } from '../components/rules.js';
import { TransactionDialog } from './transaction-dialog.js';

const EMPTY = { account: '', category: '', from: '', to: '', min: '', max: '', payee: '', tag: '' };

export default function Transactions() {
  useTitle('Transactions');
  useGuide('transactions');
  const { query } = useLocation();
  const [f, setF] = useState({ ...EMPTY, category: query.category || '' });
  const [typing, setTyping] = useState(f.payee);
  const [page, setPage] = useState(1);
  const [since, setSince] = useState(() => new Date().toISOString());
  const [newer, setNewer] = useState(0);
  const cats = useCategories();
  const accounts = useList('/accounts', {}, ['share']);
  const params = {
    account: f.account ? [f.account] : undefined,
    category: f.category || undefined,
    from: f.from || undefined,
    to: f.to || undefined,
    min: f.min || undefined,
    max: f.max || undefined,
    payee: f.payee || undefined,
    tag: f.tag || undefined,
    limit: pageSize.value,
    offset: offsetOf(page, newer),
  };
  const res = useApi('/transactions', params, []);
  const d = /** @type {any} */ (res.data);
  const all = /** @type {any[]} */ (accounts.data) || [];

  useEffect(() => {
    const t = setTimeout(() => set('payee')(typing), 300);
    return () => clearTimeout(t);
  }, [typing]);
  useEffect(() => {
    // Rows that arrive while reading are counted, not slipped into the page (S12.1.3).
    api.get('/transactions/newer', { since }).then((r) => setNewer(r.count), () => {});
  }, [changes.value.import || 0]);

  const set = (/** @type {string} */ k) => (/** @type {string} */ v) => {
    setF({ ...f, [k]: v });
    setPage(1);
  };
  const fresh = () => {
    setSince(new Date().toISOString());
    setNewer(0);
    setPage(1);
    res.reload();
  };
  const field = (/** @type {string} */ id) => ({ id: 'f-' + id });
  return html`
    <div class="toolbar">
      <label class="sr-only" for="f-search">Search payee or memo</label>
      <input class="in" ...${field('search')} style=${{
        maxWidth: '240px',
      }} placeholder="Search payee or memo…"
        value=${typing} onInput=${(/** @type {any} */ e) => setTyping(e.currentTarget.value)} />
      <label class="sr-only" for="f-account">Account</label>
      <select class="in" ...${field('account')} style=${{ width: '170px' }} value=${f.account}
        onChange=${(/** @type {any} */ e) => set('account')(e.currentTarget.value)}>
        <option value="">All accounts</option>${all.map((a) =>
          html`<option value=${a.id}>${a.name}</option>`
        )}</select>
      <label class="sr-only" for="f-category">Category</label>
      <select class="in" ...${field('category')} style=${{ width: '190px' }} value=${f.category}
        onChange=${(/** @type {any} */ e) => set('category')(e.currentTarget.value)}>
        <option value="">All categories</option><option value="none">Uncategorised</option>
        ${cats.list.map((c) => html`<option value=${c.id}>${c.path}</option>`)}</select>
      <span class="spacer"></span>
      <button type="button" class="btn" onClick=${() => openRules().then(fresh)}>Rules</button>
      <button type="button" class="btn" disabled=${!all.some((a) => canAdd('Txn', a))}
        onClick=${() =>
          openDialog(ImportDialog, { accounts: all }).then(
            fresh,
          )}><${Icon} name="upload" /> Import</button>
      <button type="button" class="btn primary" disabled=${!all.some((a) => canAdd('Txn', a))}
        onClick=${() =>
          openDialog(TransactionDialog, { accounts: all }).then((v) =>
            v && fresh()
          )}><${Icon} name="plus" /> Add</button>
    </div>
    <details class="mt" style=${{ marginBottom: '12px' }}>
      <summary class="small">More filters</summary>
      <div class="row mt">
        <div
          class="field"><label for="f-from">From</label><input class="in" id="f-from" type="date" value=${f
            .from}
          onInput=${(/** @type {any} */ e) => set('from')(e.currentTarget.value)} /></div>
        <div
          class="field"><label for="f-to">To</label><input class="in" id="f-to" type="date" value=${f
            .to}
          onInput=${(/** @type {any} */ e) => set('to')(e.currentTarget.value)} /></div>
        <div
          class="field"><label for="f-min">At least</label><input class="in" id="f-min" inputmode="decimal" value=${f
            .min}
          onInput=${(/** @type {any} */ e) =>
            set('min')(e.currentTarget.value)} placeholder="0.00" /></div>
        <div
          class="field"><label for="f-max">At most</label><input class="in" id="f-max" inputmode="decimal" value=${f
            .max}
          onInput=${(/** @type {any} */ e) => set('max')(e.currentTarget.value)} /></div>
        <div class="field"><label for="f-tag">Tag</label><input class="in" id="f-tag" value=${f.tag}
          onInput=${(/** @type {any} */ e) =>
            set('tag')(e.currentTarget.value.trim().toLowerCase())} /></div>
      </div>
      <button type="button" class="btn sm" onClick=${() => {
        setF(EMPTY);
        setTyping('');
        setPage(1);
      }}>Clear the filters</button>
    </details>
    ${f.category === 'none' && d?.items.length
      ? html`
        <div class="notice warn" style=${{ marginBottom: '12px' }}>
          <${Icon} name="info" />
          <div><b>Uncategorised.</b> Select rows to categorise them together.</div>
        </div>
      `
      : null}
    ${res.error
      ? html`<${Failed} error=${res.error} />`
      : !d
      ? html`<${Loading} lines=${8} />`
      : d.items.length
      ? html`<${TxTable} rows=${d.items} onChanged=${res.reload} accounts=${all} />`
      : html`<${Empty}>${
        all.length ? 'No transactions match.' : 'No accounts yet: make one on Accounts.'
      }</${Empty}>`}
    ${d
      ? html`
        <${Pager} label="tx" shown=${d.items.length} page=${page} total=${d.total} newer=${newer}
          onNewer=${fresh} onPage=${setPage} />
      `
      : null}
  `;
}
