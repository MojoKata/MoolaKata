// A linked household's window (requirements S12.10): what another household shares with you,
// never mixed with this household's. The same frame, read only: its avatar and name, a colour
// you choose for it, a header strip with its sync and lock, and only the kinds it shares with
// you. While its copy is locked, only its name and the request for its access key show.
import { useEffect, useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { ago, date, initials, quantity } from '../app/format.js';
import { session } from '../store/session.js';
import { collapsed, helpOpen, privacy } from '../store/prefs.js';
import { HelpCorner, HelpPane, useGuide } from '../components/help.js';
import { Icon } from '../components/icon.js';
import { Avatar, Empty, Failed, Loading, Tabs } from '../components/bits.js';
import { Amt } from '../components/amount.js';
import { Dialog, openDialog } from '../components/dialog.js';
import { errAt, Field, FormError } from '../components/fields.js';
import { toast } from '../components/toast.js';
import { TimeChart } from '../charts/chart.js';
import { Panel, PANEL_TABS } from '../components/taxpanels.js';
import { Dec, dec } from '../app/dec.js';
import { Record as Rec } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { saveOne } from '../components/draft-form.js';

const HUES = /** @type {Record<string, string>} */ ({
  teal: '#4fc6d6',
  violet: '#a98bff',
  amber: '#e0a93a',
  rose: '#e9799f',
  green: '#5fbf86',
  blue: '#6f9cf2',
});
/** Which kinds make which screens, in the navigation's order (S12.10.3.4). */
const SCREENS = /** @type {[string, string, string, string[]][]} */ ([
  ['', 'Dashboard', 'dashboard', ['account', 'portfolio', 'budget', 'tax-book', 'projection']],
  ['accounts', 'Accounts', 'bank', ['account']],
  ['positions', 'Positions', 'candles', ['account']],
  ['portfolios', 'Portfolios', 'pie', ['portfolio']],
  ['transactions', 'Transactions', 'tx', ['account']],
  ['projections', 'Projections', 'trend', ['projection']],
  ['budgets', 'Budgets', 'target', ['budget']],
  ['gifts', 'Gifts', 'gift', ['gift-plan', 'person']],
  ['giving', 'Giving', 'heart', ['giving-plan']],
  ['taxes', 'Taxes', 'tax', ['tax-book']],
  ['receipts', 'Receipts', 'receipt', ['receipts']],
]);

export default function LinkedWindow() {
  const { path } = useLocation();
  const [, , , id, sub = '', subId = '', tab = ''] = path.split('/');
  const res = useApi(`/linked/${id}`);
  const st = /** @type {any} */ (res.data);
  if (res.error) {
    return html`
      <div class="content">
        <${Failed} error=${res.error} />
      </div>
    `;
  }
  if (!st) {
    return html`
      <div class="content">
        <${Loading} lines=${4} />
      </div>
    `;
  }
  return html`
    <${Frame} id=${id} st=${st} reload=${res.reload} sub=${sub} subId=${subId}
      tab=${tab} />
  `;
}

/**
 * @param {{ id: string, st: any, reload: () => void, sub: string, subId: string, tab: string }} p
 */
function Frame({ id, st, reload, sub, subId, tab }) {
  const h = st.household;
  const me = session.value.user;
  const items = useList(h.locked ? '' : `/linked/${id}/items`);
  const rows = /** @type {any[]} */ (items.data) || [];
  const files = useList(h.locked ? '' : `/linked/${id}/files`);
  useEffect(() => {
    document.title = `${h.name || h.serverName} · MoolaKata`;
    document.body.classList.toggle('privacy', privacy.value);
  }, [h.name, privacy.value]);
  useEffect(() => {
    // A copy that locks while the window is open returns to the request for its words.
    if (items.error?.status === 423) reload();
  }, [items.error]);
  const kinds = new Set(rows.map((r) => r.kind));
  if (/** @type {any[]} */ (files.data)?.length) kinds.add('receipts');
  const nav = SCREENS.filter(([, , , k]) => k.some((x) => kinds.has(x)));
  const base = `/ui/linked/${id}`;
  const lock = useSubmit(async () => {
    await api.post(`/linked/${id}/lock`);
    toast('Locked');
    reload();
  });
  const current = sub === 'account'
    ? 'accounts'
    : sub === 'portfolio'
    ? 'portfolios'
    : sub === 'budget'
    ? 'budgets'
    : sub === 'tax-book'
    ? 'taxes'
    : sub;
  const title = h.locked
    ? 'Locked'
    : { account: 'Account', portfolio: 'Portfolio', budget: 'Budget', 'tax-book': 'Tax book' }[
      sub
    ] || SCREENS.find(([k]) => k === current)?.[1] || 'Dashboard';
  return html`<div class=${
    'app peer' + (collapsed.value ? ' collapsed' : '') +
    (helpOpen.value ? ' help-open' : '')
  } style=${{ '--peer': HUES[h.colour] || HUES.teal }}>
    <aside class="side" aria-label=${h.name}>
      <div class="brand"><${HouseAvatar} h=${h} />
        <div class="brand-text"><div class="brand-name">${h.name || h.serverName}</div>
          <div class="brand-ver">${h.serverName} · read only</div></div></div>
      <button type="button" class="collapse-btn" aria-label=${
    collapsed.value ? 'Open the sidebar' : 'Collapse the sidebar'
  } onClick=${() => (collapsed.value = !collapsed.value)}><${Icon} name="chev" /></button>
      <nav>${
    h.locked ? null : nav.map(([k, label, icon]) =>
      html`
        <a class=${'nav-item' + (current === k ? ' active' : '')} href=${`${base}/${k}`}
          aria-current=${current === k ? 'page' : undefined}><${Icon} name=${icon} /><span
                    class="nav-label">${label}</span></a>
      `
    )
  }</nav>
      <div class="user-tile">
        <${Avatar} name=${me.displayName} image=${me.avatar} id=${me.id} />
        <div class="user-text"><b>${me.displayName}</b><span>viewing ${h.serverName}</span></div>
        <button type="button" class="icon-btn" aria-label=${`Colour for ${h.name}`}
          data-tip=${`Colour for ${h.name}`} onClick=${() =>
    openDialog(ColourDialog, { id, h }).then((x) => x && reload())}><${Icon}
            name="palette" /></button>
      </div>
    </aside>
    <main id="main">
      ${helpOpen.value ? null : html`<${HelpCorner} />`}
      <div class="topbar"><h1><span class="crumb">${h.name} ›</span><span>${title}</span></h1>
        <button type="button" class="icon-btn" aria-pressed=${privacy.value ? 'true' : 'false'}
          aria-label=${
    privacy.value ? 'Show amounts' : 'Hide amounts (privacy mode)'
  } onClick=${() => (privacy.value = !privacy.value)}><${Icon} name=${
    privacy.value ? 'eye-off' : 'eye'
  } /></button></div>
      <div class="content">${
    h.locked ? html`<${Locked} id=${id} st=${st} reload=${reload} />` : html`
      <div class="peer-strip" data-help="strip"><${Icon} name="link" /><b>${h.serverName}</b>
        <span>read only</span><span class="dim">synced ${ago(h.syncedAt)}</span>
        <span class="dim">unlocked by ${st.unlockedBy} · locks after ${Math.round(
          (st.locksInSeconds || 0) / 60,
        )} min unused</span><span class="spacer"></span><button type="button" class="btn sm"
          disabled=${lock.busy} onClick=${() => lock.run().catch(() => {})}><${Icon}
            name="lock" /> Lock now</button></div>
      ${items.error
        ? html`<${Failed} error=${items.error} />`
        : !items.data
        ? html`<${Loading} lines=${6} />`
        : html`<${Screen} id=${id} rows=${rows} sub=${sub} subId=${subId} tab=${tab} />`}
    `
  }</div>
    </main>
    ${helpOpen.value ? html`<${HelpPane} />` : null}
  </div>`;
}

/** @param {{ h: any, size?: number }} p */
function HouseAvatar({ h, size }) {
  const av = h.avatar || {};
  const style = size
    ? { width: `${size}px`, height: `${size}px`, fontSize: `${size / 2.6}px` }
    : {};
  if (av.kind === 'image') {
    return html`<span class="brand-av" style=${style}><img src=${av.image} alt="" /></span>`;
  }
  return html`<span class="brand-av" style=${{ ...style, background: av.color || '#7a4b9c' }}>${
    av
      .initials || initials(h.name || '?')
  }</span>`;
}

/** The request for the access key (S11.9.3, S12.10.4). */
/** @param {{ id: string, st: any, reload: () => void }} p */
function Locked({ id, st, reload }) {
  useGuide('linked-locked');
  const h = st.household;
  const [words, setWords] = useState('');
  const go = useSubmit(async () => {
    await api.post(`/linked/${id}/unlock`, { words });
    setWords('');
    reload();
  });
  return html`<form class="card locked-card" onSubmit=${(/** @type {Event} */ e) => {
    e.preventDefault();
    go.run().catch(() => {});
  }}>
    <${HouseAvatar} h=${h} size=${56} />
    <h3>${h.name}</h3>
    <p class="dim">What ${h.name} share with you is kept encrypted on this server. To open it,
      enter its access key: the 12 words in your household's password manager.</p>
    <p class="small dim">synced ${ago(st.pulledAt || h.syncedAt)}${
    st.waiting ? ` · ${st.waiting} change${st.waiting === 1 ? '' : 's'} waiting` : ''
  } · locked</p>
    ${
    st.hasKey
      ? html`
        <${Field} label="Access key" id="access-key" error=${errAt(go.error, 'words') ||
          (go.error ? go.error.message : null)}
          hint="12 words, separated by spaces.">
          <textarea class="in mono" rows="3" value=${words} onInput=${(/** @type {any} */ e) =>
            setWords(e.currentTarget.value)} autocomplete="off"
            spellcheck="false"></textarea>
          </${Field}>
          <button class="btn primary" disabled=${go.busy || !words.trim()}><${Icon} name="lock" />
          Open</button>
          <p class="small dim">Once open, it stays open for everyone it shares with, each seeing only
          what names them, until it goes unused.</p>
      `
      : html`<p class="notice">An admin here hasn't created this copy's access key yet:
        Settings › Linked servers.</p>`
  }
  </form>`;
}

/** The colour a person chose for a linked household's window. */
class ColourRec extends Rec {
  /** @override */
  static prefix = 'LkCol';
  /** @override */
  static fields = FIELDS.ColourRecord;
}

/** @param {{ close: (v?: any) => void, id: string, h: any }} p */
function ColourDialog({ close, id, h }) {
  // The colour chosen is a record of the chooser's (S12.10.3.2).
  const save = useSubmit(async (/** @type {string} */ colour) => {
    const row = h.colourId
      ? { id: h.colourId, version: h.colourVersion, linkId: id, colour: h.colour }
      : null;
    await saveOne(ColourRec, row, { linkId: id, colour });
    close(true);
  });
  return html`
    <${Dialog} title=${`Colour for ${h.name}`} close=${close} onSubmit=${() => close()}>
      <p class="small dim" style=${{ marginTop: 0 }}>Tints this household's window for you. Other
          people choose their own.</p>
      <div class="field"><label>Colour</label><div class="swatches">${Object.entries(HUES).map((
        [k, v],
      ) =>
        html`
          <button type="button" class=${'swatch' + (h.colour === k ? ' on' : '')} style=${{
            background: v,
          }} aria-label=${k}
            aria-pressed=${h.colour === k ? 'true' : 'false'} onClick=${() =>
              save.run(k).catch(() => {})}></button>
        `
      )}</div></div>
      <${FormError} error=${save.error} />
      </${Dialog}>
  `;
}

/**
 * The screens, read only, from what arrived.
 * @param {{ id: string, rows: any[], sub: string, subId: string, tab: string }} p
 */
function Screen({ id, rows, sub, subId, tab }) {
  const base = `/ui/linked/${id}`;
  const of = (/** @type {string} */ k) => rows.filter((r) => r.kind === k);
  if (sub === 'account' && subId) return html`<${Account} base=${base} aid=${subId} tab=${tab} />`;
  if (sub === 'portfolio' && subId) return html`<${Portfolio} pid=${subId} />`;
  if (sub === 'budget' && subId) {
    return html`<${Budget} base=${base} bid=${subId} tab=${tab || 'month'} />`;
  }
  if (sub === 'positions') return html`<${Positions} rows=${of('account')} />`;
  if (sub === 'tax-book' && subId) {
    return html`<${TaxBook} base=${base} bid=${subId} tab=${tab || 'gains'} />`;
  }
  if (sub === 'accounts') return html`<${Accounts} base=${base} rows=${of('account')} />`;
  if (sub === 'transactions') return html`<${AllTransactions} rows=${of('account')} />`;
  if (sub === 'portfolios') {
    return html`
      <${List} guide="linked-portfolios" rows=${of('portfolio')}
        href=${(/** @type {any} */ r) => `${base}/portfolio/${r.id}`} value=${(
          /** @type {any} */ r,
        ) => r.row?.value} />
    `;
  }
  if (sub === 'budgets') {
    return html`
      <${List} guide="linked-budgets" rows=${of('budget')}
        href=${(/** @type {any} */ r) => `${base}/budget/${r.id}`} />
    `;
  }
  if (sub === 'taxes') {
    return html`
      <${List} guide="linked-taxes" rows=${of('tax-book')}
        href=${(/** @type {any} */ r) => `${base}/tax-book/${r.id}`} label=${(
          /** @type {any} */ r,
        ) => r.row?.label || r.name} />
    `;
  }
  if (sub === 'projections') return html`<${Projections} rows=${of('projection')} />`;
  if (sub === 'giving') return html`<${Giving} rows=${of('giving-plan')} />`;
  if (sub === 'gifts') return html`<${Gifts} rows=${of('gift-plan')} people=${of('person')} />`;
  if (sub === 'receipts') return html`<${Receipts} id=${id} />`;
  return html`<${Dashboard} base=${base} rows=${rows} />`;
}

/** @param {{ base: string, rows: any[] }} p */
function Dashboard({ base, rows }) {
  useGuide('linked-dashboard');
  if (!rows.length) return html`<${Empty}>Nothing is shared with you yet.</${Empty}>`;
  const accounts = rows.filter((r) => r.kind === 'account');
  // A newer MoolaKata on the other side may share kinds this one can't show yet (version skew).
  const unknown = rows.filter((r) => !KIND[r.kind]);
  rows = rows.filter((r) => KIND[r.kind]);
  const total = Dec.sum(accounts.map((r) => dec(r.row?.balance)));
  return html`
    ${accounts.length
      ? html`
        <div class="grid g4">
          <div class="card kpi">
            <div class="label">Accounts shared with
                  you</div>
            <div class="value">
              <${Amt} v=${String(total)} cents=${false} />
            </div>
            <div
              class="delta dim">${accounts.length} account${accounts.length === 1 ? '' : 's'}, as of
                  their last sync</div>
          </div>
        </div>
      `
      : null}
    ${unknown.length
      ? html`
        <p
          class="notice mt">${unknown.length} more item${unknown.length === 1
            ? ' is'
            : 's are'} shared with you by a newer MoolaKata, which this one can't show yet.</p>
      `
      : null}
    <div class="card mt"><h3>Shared with you</h3>${rows.map((r) =>
      html`
        <div
          class="list-item"><div class="grow"><a href=${`${base}/${
            r.kind === 'account'
              ? 'account'
              : r.kind === 'portfolio'
              ? 'portfolio'
              : r.kind === 'budget'
              ? 'budget'
              : r.kind === 'tax-book'
              ? 'tax-book'
              : r.kind === 'projection'
              ? 'projections'
              : r.kind === 'gift-plan' || r.kind === 'person'
              ? 'gifts'
              : 'giving'
          }${
            ['account', 'portfolio', 'budget', 'tax-book'].includes(r.kind) ? '/' + r.id : ''
          }`}>${r
            .row?.label || r.name}</a><div class="small dim">${KIND[r.kind] || r.kind} · ${r
            .ownerName}</div></div>${r.row?.balance != null
            ? html`<${Amt} v=${r.row.balance} />`
            : r.row?.value != null
            ? html`<${Amt} v=${r.row.value} />`
            : null}</div>
      `
    )}</div>
  `;
}

const KIND = /** @type {Record<string, string>} */ ({
  account: 'Account',
  portfolio: 'Portfolio',
  budget: 'Budget',
  'gift-plan': 'Gift plan',
  person: 'Person',
  'giving-plan': 'Giving plan',
  'tax-book': 'Tax book',
  projection: 'Projection',
});

/** @param {{ base: string, rows: any[] }} p */
function Accounts({ base, rows }) {
  useGuide('linked-accounts');
  if (!rows.length) return html`<${Empty}>No accounts are shared with you.</${Empty}>`;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table
          class="t">
          <caption class="sr-only">Accounts</caption>
          <thead>
            <tr>
              <th>Account</th>
              <th>Owner</th>
              <th class="num">Balance</th>
              <th class="num">30 days</th>
            </tr>
          </thead>
          <tbody>${rows.map((r) =>
            html`
              <tr>
                <td><a href=${`${base}/account/${r.id}`}><b>${r
                  .name}</b></a><div class="small dim">${[
                  r.row?.institution,
                  r.row?.typeLabel,
                ].filter(Boolean).join(' · ')}</div></td>
                <td class="small dim">${r.ownerName}</td>
                <td
                  class="num">${r.row ? html`<${Amt} v=${r.row.balance} />` : '—'}</td>
                <td class="num">${r.row
                    ?.change != null
                  ? html`<${Amt} v=${r.row.change} signed />`
                  : '—'}</td>
              </tr>
            `
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}

/** @param {{ base: string, aid: string, tab: string }} p */
function Account({ base, aid, tab }) {
  useGuide('linked-account');
  const d = useApi(`/accounts/${aid}`);
  const s = useApi(`/accounts/${aid}/series`, { range: 'All' });
  const a = /** @type {any} */ (d.data);
  if (d.error) return html`<${Failed} error=${d.error} />`;
  if (!a) return html`<${Loading} lines=${5} />`;
  const tabs = /** @type {[string, string][]} */ ([
    ['overview', 'Overview'],
    ...(a.investing ? [['holdings', 'Holdings']] : []),
    ['transactions', 'Transactions'],
  ]);
  const current = tabs.some(([k]) => k === tab) ? tab : 'overview';
  const series = /** @type {any} */ (s.data);
  return html`
    <div class="toolbar"><div><div class="name" style=${{ fontSize: '16px' }}><b>${a.name}</b></div>
      <div class="small dim">${[a.institution, a.typeLabel, a.ownerName].filter(Boolean).join(
        ' · ',
      )}</div></div><span class="spacer"></span><div style=${{
        fontSize: '22px',
        fontWeight: 650,
      }}><${Amt} v=${a.balance} /></div></div>
    <${Tabs} tabs=${tabs} current=${current} base=${`${base}/account/${aid}`} />
    ${current === 'overview'
      ? html`<div class="card"><h3>Balance</h3>${
        series
          ? html`<${TimeChart} label=${`${a.name} over time`} series=${[{
            name: a.name,
            color: /** @type {HTMLElement | null} */ (document.querySelector('.app.peer'))?.style
              .getPropertyValue('--peer') || HUES.teal,
            area: true,
            points: series.points.map((/** @type {any} */ p) => [p.date, p.value]),
          }]} />`
          : s.error
          ? html`<p class="small dim">Its history hasn't arrived.</p>`
          : html`<${Loading} lines=${4} />`
      }</div>`
      : current === 'holdings'
      ? html`<${Holdings} aid=${aid} />`
      : html`<${Txns} aid=${aid} />`}
  `;
}

/** @param {{ aid: string }} p */
function Holdings({ aid }) {
  const res = useApi(`/accounts/${aid}/holdings`);
  const h = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!h) return html`<${Loading} lines=${4} />`;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table
          class="t">
          <caption class="sr-only">Holdings</caption>
          <thead>
            <tr>
              <th>Holding</th>
              <th
                class="num">Quantity</th>
              <th class="num">Value</th>
              <th class="num">Gain</th>
            </tr>
          </thead>
          <tbody>${h.holdings.map((/** @type {any} */ x) =>
            html`
              <tr>
                <td><b>${x.symbol}</b><div class="small dim">${x.name || ''}</div></td>
                <td
                  class="num">${quantity(x.quantity)}</td>
                <td class="num">${x.value ? html`<${Amt} v=${x.value} />` : '—'}</td>
                <td class="num">${x.gain ? html`<${Amt} v=${x.gain} signed />` : '—'}</td>
              </tr>
            `
          )}<tr><td>Cash</td><td></td><td class="num"><${Amt} v=${h
            .cash} /></td><td></td></tr></tbody>
        </table>
      </div>
    </div>
  `;
}

/** @param {{ aid: string }} p */
function Txns({ aid }) {
  const res = useApi('/transactions', { account: aid });
  const v = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} lines=${6} />`;
  return html`<${TxList} items=${v.items} />`;
}

/** @param {{ items: any[] }} p */
function TxList({ items }) {
  if (!items.length) return html`<${Empty}>No transactions.</${Empty}>`;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table
          class="t">
          <caption class="sr-only">Transactions</caption>
          <thead>
            <tr>
              <th>Date</th>
              <th>Payee</th>
              <th>Category</th>
              <th class="num">Amount</th>
            </tr>
          </thead>
          <tbody>${items.map((t) =>
            html`
              <tr>
                <td class="small dim">${date(t.date)}</td>
                <td>${t.payee || t.kind}${t.memo
                  ? html`<div class="small dim">${t.memo}</div>`
                  : null}</td>
                <td class="small dim">${t.categoryLabel || ''}</td>
                <td class="num">
                  <${Amt}
                    v=${t.amount} signed />
                </td>
              </tr>
            `
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}

/** @param {{ rows: any[] }} p */
function AllTransactions({ rows }) {
  useGuide('linked-transactions');
  const [which, setWhich] = useState(rows[0]?.id || '');
  return html`<div class="toolbar"><select class="in" aria-label="Account" value=${which}
    onChange=${(/** @type {any} */ e) => setWhich(e.currentTarget.value)}>${
    rows.map((r) => html`<option value=${r.id}>${r.name}</option>`)
  }</select></div>${which ? html`<${Txns} aid=${which} />` : null}`;
}

/**
 * @param {{ guide: string, rows: any[], href: (r: any) => string, value?: (r: any) => any,
 *   label?: (r: any) => string }} p
 */
function List({ guide, rows, href, value, label }) {
  useGuide(guide);
  if (!rows.length) return html`<${Empty}>Nothing of this kind is shared with you.</${Empty}>`;
  return html`<div class="card">${
    rows.map((r) =>
      html`
        <div
          class="list-item"><div class="grow"><a href=${href(r)}><b>${label
            ? label(r)
            : r.name}</b></a><div class="small dim">${r
            .ownerName}</div></div>${value && value(r) != null
            ? html`<${Amt} v=${value(r)} />`
            : null}</div>
      `
    )
  }</div>`;
}

/** @param {{ pid: string }} p */
function Portfolio({ pid }) {
  useGuide('linked-portfolios');
  const p = useApi(`/portfolios/${pid}`);
  const h = useApi(`/portfolios/${pid}/holdings`);
  const r = useList(`/portfolios/${pid}/returns`);
  const series = useApi(`/portfolios/${pid}/series`, { range: 'All' });
  const pf = /** @type {any} */ (p.data);
  const hold = /** @type {any} */ (h.data);
  const ret = /** @type {any[]} */ (r.data);
  if (p.error) return html`<${Failed} error=${p.error} />`;
  if (!pf) return html`<${Loading} lines=${5} />`;
  const pts = /** @type {any} */ (series.data)?.points;
  return html`
    <div class="toolbar"><b style=${{ fontSize: '16px' }}>${pf.name}</b><span class="spacer"></span>
      <span style=${{ fontSize: '22px', fontWeight: 650 }}><${Amt} v=${pf.value} /></span></div>
    ${pts?.length
      ? html`
        <div class="card mb">
          <h3>Value</h3>
          <${TimeChart} label=${`${pf.name} over time`}
            series=${[{
              name: pf.name,
              color: HUES.teal,
              area: true,
              points: pts.map((/** @type {any} */ p) => [p.date, p.value]),
            }]} />
        </div>
      `
      : null}
    ${ret?.length
      ? html`
        <div class="card">
          <h3>Returns by period</h3>
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Returns</caption>
              <thead>
                <tr><th></th>${Object.keys(ret[0].periods)
                  .map((k) => html`<th class="num">${k}</th>`)}</tr>
              </thead>
              <tbody>${ret.map((x) =>
                html`<tr><td>${x.name}</td>${
                  Object.values(x.periods).map((v) =>
                    html`<td class="num">${v == null ? '—' : `${v}%`}</td>`
                  )
                }</tr>`
              )}</tbody>
            </table>
          </div>
        </div>
      `
      : null}
    ${hold
      ? html`
        <div class="card mt" style=${{ padding: '4px 8px' }}>
          <div class="table-wrap">
            <table
              class="t">
              <caption class="sr-only">Holdings</caption>
              <thead>
                <tr>
                  <th>Holding</th>
                  <th
                    class="num">Value</th>
                  <th class="num">Weight</th>
                </tr>
              </thead>
              <tbody>${hold.holdings.map((
                /** @type {any} */ x,
              ) =>
                html`
                  <tr>
                    <td><b>${x.symbol}</b><div class="small dim">${x.name || ''}</div></td>
                    <td
                      class="num">${x.value ? html`<${Amt} v=${x.value} />` : '—'}</td>
                    <td class="num">${x
                        .weight
                      ? `${x.weight}%`
                      : '—'}</td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        </div>
      `
      : null}
  `;
}

/** @param {{ base: string, bid: string, tab: string }} p */
function Budget({ base, bid, tab }) {
  useGuide('linked-budgets');
  const tabs = /** @type {[string, string][]} */ ([
    ['month', 'This month'],
    ['trends', 'Trends'],
    ['cash-flow', 'Cash flow'],
    ['recurring', 'Recurring'],
  ]);
  return html`
    <${Tabs} tabs=${tabs} current=${tab} base=${`${base}/budget/${bid}`} />
    ${tab === 'trends'
      ? html`<${BudgetTrends} bid=${bid} />`
      : tab === 'cash-flow'
      ? html`<${BudgetFlow} bid=${bid} />`
      : tab === 'recurring'
      ? html`<${BudgetRecurring} bid=${bid} />`
      : html`<${BudgetMonth} bid=${bid} />`}
  `;
}

/** @param {{ bid: string }} p */
function BudgetMonth({ bid }) {
  const res = useApi(`/budgets/${bid}/month`);
  const m = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!m) return html`<${Loading} lines=${6} />`;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <h3 style=${{ padding: '8px 8px 0' }}>Month of ${date(m.month)}</h3>
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only">This month</caption>
          <thead>
            <tr>
              <th>Category</th>
              <th class="num">Planned</th>
              <th class="num">Spent</th>
              <th
                class="num">Left</th>
            </tr>
          </thead>
          <tbody>${m.rows.map((/** @type {any} */ r) =>
            html`
              <tr>
                <td>${r.label}</td>
                <td class="num">
                  <${Amt} v=${r.planned} />
                </td>
                <td class="num"
                >
                  <${Amt} v=${r.actual} />
                </td>
                <td class="num">
                  <${Amt} v=${r.remaining} signed />
                </td>
              </tr>
            `
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}

/** @param {{ bid: string }} p */
function BudgetTrends({ bid }) {
  const res = useList(`/budgets/${bid}/trends`);
  const rows = /** @type {any[] | null} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!rows) return html`<${Loading} lines=${4} />`;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table
          class="t">
          <caption class="sr-only">Planned and spent by month</caption>
          <thead>
            <tr>
              <th>Month</th>
              <th class="num">Planned</th>
              <th class="num">Spent</th>
            </tr>
          </thead>
          <tbody>${rows.map((r) =>
            html`
              <tr>
                <td>${date(r.month)}</td>
                <td class="num">
                  <${Amt} v=${r.planned} />
                </td>
                <td
                  class="num">
                  <${Amt} v=${r.actual} />
                </td>
              </tr>
            `
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}

/** @param {{ bid: string }} p */
function BudgetFlow({ bid }) {
  const res = useApi(`/budgets/${bid}/cash-flow`);
  const f = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!f) return html`<${Loading} lines=${4} />`;
  const side = (/** @type {string} */ title, /** @type {any[]} */ rows) =>
    html`<div class="card"><h3>${title}</h3>${
      rows.map((r) =>
        html`<div class="list-item"><span class="grow">${r.name}</span><${Amt} v=${r.amount} /></div>`
      )
    }</div>`;
  return html`<div class="grid g2">${side(`Income · ${date(f.month)}`, f.sources)}${
    side('Spending', f.uses)
  }</div>`;
}

/** @param {{ bid: string }} p */
function BudgetRecurring({ bid }) {
  const res = useList(`/budgets/${bid}/recurring`);
  const rows = /** @type {any[] | null} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!rows) return html`<${Loading} lines=${4} />`;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table
          class="t">
          <caption class="sr-only">Recurring</caption>
          <thead>
            <tr>
              <th>Payee</th>
              <th>Every</th>
              <th
              >Next</th>
              <th class="num">Usual</th>
            </tr>
          </thead>
          <tbody>${rows.map((r) =>
            html`
              <tr>
                <td>${r.payee}<div class="small dim">${r.accountName}</div></td>
                <td>${r.every}</td>
                <td>${date(r.next)}</td>
                <td class="num">
                  <${Amt} v=${r.usual} />
                </td>
              </tr>
            `
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}

/**
 * What the shared accounts hold, each as its holdings arrived.
 * @param {{ rows: any[] }} p
 */
function Positions({ rows }) {
  useGuide('linked-positions');
  const investing = rows.filter((r) => r.row?.investing);
  if (!investing.length) return html`<${Empty}>No investing account is shared with you.</${Empty}>`;
  return html`${
    investing.map((r) =>
      html`
        <h3 style=${{ margin: '12px 0 6px' }}>${r.name}</h3>
        <${Holdings} aid=${r.id} />
      `
    )
  }`;
}

/** @param {{ base: string, bid: string, tab: string }} p */
function TaxBook({ base, bid, tab }) {
  useGuide('linked-taxes');
  const tabs = PANEL_TABS;
  return html`
    <${Tabs} tabs=${tabs} current=${tab} base=${`${base}/tax-book/${bid}`} />
    <${Panel} b=${{ id: bid }} tab=${tab} />
  `;
}

/** @param {{ rows: any[] }} p */
function Projections({ rows }) {
  useGuide('linked-projections');
  return html`<div class="card">${
    rows.map((r) =>
      html`
        <div
          class="list-item"><div class="grow"><b>${r.name}</b><div class="small dim">${r.row
            ?.headline || ''}</div></div><span class="small dim">${r.row?.status || ''}</span></div>
      `
    )
  }</div>`;
}

/** @param {{ rows: any[] }} p */
function Giving({ rows }) {
  useGuide('linked-giving');
  return html`${rows.map((r) => html`<${GivingYear} year=${r.name} />`)}`;
}

/** @param {{ year: string }} p */
function GivingYear({ year }) {
  const res = useApi('/giving', { year });
  const g = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!g) return html`<${Loading} lines=${3} />`;
  return html`
    <div class="grid g4 mt">
      <div class="card kpi">
        <div class="label">Given in ${g
          .year}</div>
        <div class="value">
          <${Amt} v=${g.given} cents=${false} />
        </div>
        <div
          class="delta dim">target <${Amt} v=${g.target} cents=${false} /></div>
      </div>
      <div
        class="card kpi">
        <div class="label">Pledged</div>
        <div class="value">
          <${Amt} v=${g.pledged}
            cents=${false} />
        </div>
      </div>
    </div>
    <${Donations} year=${year} />
  `;
}

/** @param {{ year: string }} p */
function Donations({ year }) {
  const res = useList('/giving/donations', { year });
  const rows = /** @type {any[] | null} */ (res.data);
  if (res.error || !rows?.length) return null;
  return html`
    <div class="card mt" style=${{ padding: '4px 8px' }}>
      <h3 style=${{
        padding: '8px 8px 0',
      }}>Donations in ${year}</h3>
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only"
          >Donations</caption>
          <tbody>${rows.map((d) =>
            html`
              <tr>
                <td class="dim">${date(d.date)}</td>
                <td>${d.organisationName || d.name ||
                  ''}</td>
                <td class="num">
                  <${Amt} v=${d.amount} />
                </td>
              </tr>
            `
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}

/** @param {{ rows: any[], people: any[] }} p */
function Gifts({ rows, people }) {
  useGuide('linked-gifts');
  return html`${
    people.length
      ? html`<div class="card"><h3 data-help="people">People shared with you</h3>${
        people.map((p) => html`<${SharedPerson} person=${p} />`)
      }</div>`
      : null
  }${rows.map((r) => html`<${PersonGifts} person=${r} />`)}`;
}

/** A person shared on their own (S10.3): their name, birthday and relationships. */
/** @param {{ person: any }} p */
function SharedPerson({ person }) {
  const res = useList(`/persons/${person.id}/relations`);
  const rel = /** @type {any[]} */ (res.data);
  const row = person.row || {};
  const born = row.birthMonth
    ? `born ${MONTHS[row.birthMonth - 1]} ${row.birthDay || ''}${
      row.birthYear ? ', ' + row.birthYear : ''
    }`
    : '';
  return html`
    <div class="list-item">
      <div class="grow">${person.name}<div class="small dim">${[
        born,
        ...(rel || []).map((x) => `${x.word} of ${x.name}`),
      ].filter(Boolean).join(' · ') || 'shared by ' + person.ownerName}</div></div>
    </div>
  `;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** @param {{ person: any }} p */
function PersonGifts({ person }) {
  const res = useList('/gifts', { person: person.id });
  const g = /** @type {any[]} */ (res.data);
  return html`<div class="card mt"><h3>${person.name}</h3>${
    res.error
      ? html`<${Failed} error=${res.error} />`
      : !g
      ? html`<${Loading} lines=${2} />`
      : g.length
      ? g.map((x) =>
        html`
          <div
            class="list-item"><div class="grow">${x.description}<div class="small dim">${x
              .occasionLabel} · ${x.status}</div></div>${x.cost
              ? html`<${Amt} v=${x.cost} />`
              : null}</div>
        `
      )
      : html`<p class="small dim">No gifts.</p>`
  }</div>`;
}

/** @param {{ id: string }} p */
function Receipts({ id }) {
  useGuide('linked-receipts');
  const res = useList(`/linked/${id}/files`);
  const v = /** @type {any[]} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} lines=${4} />`;
  if (!v.length) return html`<${Empty}>No receipts came with what is shared with you.</${Empty}>`;
  return html`<div class="card">${
    v.map((f) =>
      // A receipt still on its way (S11.4): listed with what came with it, opened once it has.
      f.arrived === false
        ? html`
          <div
            class="list-item"><${Icon} name="receipt" /><span class="grow">${f.meta.payee ||
              'A receipt'}<div class="small dim">${f.meta.date
              ? date(f.meta.date)
              : ''}</div></span>${f.meta.amount ? html`<${Amt} v=${f.meta.amount} />` : null}<span
              class="pill warn" title="Asked for again at the next exchange">not arrived</span></div>
        `
        : html`
          <a class="list-item" href=${`/ui/api/linked/${id}/files/${f.id}`} target="_blank"
            rel="noopener" style=${{ color: 'inherit' }}>${f.thumbnail
              ? html`<img src=${f.thumbnail} alt="" style=${{
                width: '40px',
                height: '40px',
                objectFit: 'cover',
                borderRadius: '6px',
              }} />`
              : html`<${Icon} name="receipt" />`}<span class="grow">${f.meta.payee ||
              'A receipt'}<div
                  class="small dim">${f.meta.date
                    ? date(f.meta.date)
                    : ''}</div></span>${f.meta.amount
                    ? html`<${Amt} v=${f.meta.amount} />`
                    : null}</a>
        `
    )
  }</div>`;
}
