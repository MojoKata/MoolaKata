// Positions (requirements S3.1, S3.9, S12.2): what is held, from open to closed, with each lot's
// holding period, and gains by year, month, account, instrument or term.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { useApi, useList } from '../app/hooks.js';
import { date, quantity, symbol } from '../kit/format.js';
import { useFormats } from '../kit/formats.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';
import { Amt } from '../kit/amount.js';
import { Chips, Empty, Failed, Loading, Tabs } from '../kit/bits.js';
import { openDialog } from '../kit/dialog.js';
import { Icon } from '../kit/icon.js';
import { Mark, OptionTrade, Settle } from '../components/optiontrade.js';
import { CorporateAction } from '../components/corporate.js';
import { Dec, dec, num } from '../kit/dec.js';
import { GroupButton, Strategies } from '../components/strategies.js';

const TABS = /** @type {[string, string][]} */ ([
  ['open', 'Open'],
  ['strategies', 'Strategies'],
  ['closed', 'Closed'],
  ['trades', 'Option Trades'],
  ['gains', 'Gains'],
]);
const SOURCE = /** @type {Record<string, string>} */ ({
  manual: 'typed mark',
  intrinsic: 'intrinsic value',
  statement: 'statement',
  trade: 'last trade',
});
/** Where a price came from, as its hover says it (S12.5). @param {string} source */
const priced = (source) => {
  const said = source === 'close' ? 'daily close' : SOURCE[source] || source;
  return said.charAt(0).toUpperCase() + said.slice(1);
};
const KIND = /** @type {[string, string][]} */ ([
  ['all', 'All'],
  ['stocks', 'Stocks and funds'],
  ['options', 'Options'],
  ['crypto', 'Crypto'],
]);
const TERM = /** @type {Record<string, string>} */ ({
  short: 'Short term',
  long: 'Long term',
  mixed: 'Mixed',
  unknown: 'Unknown: when bought is missing',
});

/** @param {{ tab?: string }} p */
export default function Positions({ tab }) {
  const fmt = useFormats();
  const current = TABS.some(([k]) => k === tab) ? /** @type {string} */ (tab) : 'open';
  useTitle('Positions');
  useGuide('positions-' + current);
  const [kind, setKind] = useState('all');
  const res = useApi('/positions', { kind }, ['import', 'prices']);
  const v = /** @type {any} */ (res.data);
  return html`
    ${v
      ? html`
        <div class="grid g4">
          <div class="card kpi">
            <div class="label">Unrealized Gain</div>
            <div class="value">
              <${Amt}
                v=${v.summary.unrealized} signed cents=${false} />
            </div>
            <div class="delta dim">open
                  positions</div>
          </div>
          <div class="card kpi">
            <div class="label">Realized ${fmt.thisYear()}</div>
            <div
              class="value">
              <${Amt} v=${v.summary.realizedThisYear} signed cents=${false} />
            </div>
            <div
              class="delta dim">short <${Amt} v=${v.summary
                .realizedShort} signed cents=${false} /> · long <${Amt} v=${v.summary
                .realizedLong} signed cents=${false} /></div>
          </div>
          <div class="card kpi">
            <div class="label">Open Positions</div>
            <div class="value">${v.open
              .length}</div>
            <div class="delta dim">${v.open.filter((/** @type {any} */ r) => r.side === 'short')
              .length} short</div>
          </div>
          <div class="card kpi">
            <div class="label">Expiring within 7 Days</div>
            <div class="value">${v.summary.expiringSoon.length}</div>
            <div class="delta">${v.summary.expiringSoon.map((/** @type {any} */ x) =>
              html`
                <span class=${'pill ' + (x.inTheMoney ? 'warn' : '')}>${symbol(x.symbol)}</span>
              `
            )}</div>
          </div>
        </div>
      `
      : null}
    <div class="toolbar mt">
      <${Chips} label="Show" value=${kind} onChange=${setKind}
        options=${KIND} />
      <span class="spacer"></span>
      <button class="btn" onClick=${() =>
        openDialog(CorporateAction, {}).then((x) => x && res.reload())}>Corporate Action…</button>
      <button class="btn primary" onClick=${() =>
        openDialog(OptionTrade, {}).then((x) => x && res.reload())}><${Icon} name="plus" /> Add
        Trade</button>
    </div>
    <${Tabs} tabs=${TABS} current=${current} base="/ui/positions" />
    ${res.error
      ? html`<${Failed} error=${res.error} />`
      : !v
      ? html`<${Loading} lines=${6} />`
      : current === 'open'
      ? html`<${Open} rows=${v.open} reload=${res.reload} />`
      : current === 'strategies'
      ? html`<${Strategies} />`
      : current === 'closed'
      ? html`<${Closed} rows=${v.closed} />`
      : current === 'trades'
      ? html`<${Trades} />`
      : html`<${Gains} />`}
  `;
}

/** @param {{ rows: any[], reload: () => void }} p */
function Open({ rows, reload }) {
  const fmt = useFormats();
  const [shown, setShown] = useState(/** @type {string | null} */ (null));
  // Legs selected to group as a strategy by hand (S3.5.1).
  const [picked, setPicked] = useState(/** @type {string[]} */ ([]));
  if (!rows.length) return html`<${Empty}>Nothing open</${Empty}>`;
  const keyOf = (/** @type {any} */ r) => r.accountId + r.instrumentId;
  const pick = (/** @type {string} */ k) =>
    setPicked(picked.includes(k) ? picked.filter((x) => x !== k) : [...picked, k]);
  const chosen = rows.filter((r) => picked.includes(keyOf(r)));
  return html`
    ${picked.length
      ? html`<div class="toolbar mb"><span class="small dim">${picked.length} selected: group them
          as a strategy.</span><span class="spacer"></span><${GroupButton} rows=${chosen}
          done=${() => {
        setPicked([]);
        reload();
      }} /></div>`
      : null}
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only">Open positions</caption>
          <thead>
            <tr>
              <th><span class="sr-only">Select</span></th>
              <th>Instrument</th>
              <th>Account</th>
              <th>Side</th>
              <th class="num">Quantity</th>
              <th class="num">Cost</th>
              <th class="num">Market Value</th>
              <th class="num">Unrealized</th>
              <th>Term</th>
            </tr>
          </thead>
          <tbody>${rows.map((r) => {
            const key = r.accountId + r.instrumentId;
            return html`
              <tr>
                <td><input
                  type="checkbox" aria-label=${'Select ' + symbol(r.symbol)}
                  checked=${picked.includes(key)} onChange=${() => pick(key)} /></td>
                <td><button type="button" class="linklike" aria-expanded=${shown === key
                  ? 'true'
                  : 'false'} onClick=${() => setShown(shown === key ? null : key)}
                  style=${{ color: 'var(--fg)', fontWeight: 600 }}>${symbol(r.symbol)}</button>${r
                      .daysToExpiry != null
                    ? html`${' '}<span class=${'pill ' + (r.daysToExpiry <= 7 ? 'warn' : '')}>${
                      r.daysToExpiry < 0 ? 'expired' : `${r.daysToExpiry}d`
                    }</span>${
                      r.inTheMoney != null
                        ? html`${' '}<span class="small dim">${r.inTheMoney ? 'ITM' : 'OTM'}</span>`
                        : null
                    }`
                    : null}${r.stale
                    ? html`${' '}<span class="pill warn">stale</span>`
                    : null}${r.name ? html`<div class="small dim">${r.name}</div>` : null}${r
                      .unknownSymbol
                    ? html`<div class="small" style=${{
                      color: 'var(--ask)',
                    }}>No price source knows ${symbol(r.symbol)}</div>`
                    : null}</td>
                <td class="small dim">${r.accountName}</td>
                <td><span class=${'pill ' + (r.side === 'short' ? 'warn' : '')}>${r.side === 'short'
                  ? 'Short'
                  : 'Long'}</span></td>
                <td class="num">${r.symbol === 'BTC'
                  ? fmt.bitcoin(r.quantity)
                  : quantity(r.quantity)}</td>
                <td class="num">${r.cost ? html`<${Amt} v=${r.cost} />` : html`
                  <span
                    class="pill warn">missing</span>
                `}</td>
                <td class="num" data-tip=${r.priceAsOf
                  ? `${priced(r.priceSource)} · as of ${date(r.priceAsOf)}`
                  : 'No price yet'}>${r.value ? html`<${Amt} v=${r.value} />` : '—'}${SOURCE[
                    r.priceSource
                  ]
                  ? html`<div class="small dim">${SOURCE[r.priceSource]}</div>`
                  : null}</td>
                <td class="num">${r.unrealized
                  ? html`
                    <${Amt} v=${r.unrealized} signed />
                    <div class="small">${r.unrealizedPct}%</div>
                  `
                  : '—'}</td>
                <td class="small">${TERM[r.term]}<div class="dim">${r.days} days</div></td>
              </tr>
                        ${shown === key
                          ? html`
                            <tr>
                              <td colspan="9">
                                <div class="small" style=${{ padding: '4px 0' }}>${r.lots.map((
                                  /** @type {any} */ l,
                                ) =>
                                  html`
                                    <div
                                      class="list-item"><span class="grow">${quantity(
                                        l.quantity,
                                      )} ${l.longTerm == null ? 'moved in' : 'bought'} ${date(
                                        l.acquiredOn,
                                      )}${l.heldFrom
                                        ? ` · held from ${date(l.heldFrom)} (a wash sale)`
                                        : ''} · ${l.longTerm == null
                                        ? 'when bought is missing, term unknown'
                                        : `${l.days} days · ${
                                          l.longTerm ? 'long term' : 'short term'
                                        }`}</span>${l.basis
                                        ? html`<${Amt} v=${l.basis} />`
                                        : html`<span class="pill warn">no basis</span>`}</div>
                                  `
                                )}${num(r.realized)
                                  ? html`<div class="dim">Realized so far: <${Amt} v=${r.realized} signed /></div>`
                                  : null}${r.expiry
                                  ? html`
                                    <div
                                      class="toolbar mt"><span class="dim">Expires ${date(
                                        r.expiry,
                                      )}</span><span class="spacer"></span><button class="btn sm"
                                        onClick=${(/** @type {Event} */ ev) => {
                                          ev.stopPropagation();
                                          openDialog(OptionTrade, {
                                            accountId: r.accountId,
                                            start: closing(r),
                                          }).then((x) => x && reload());
                                        }}>Close…</button><button class="btn sm"
                                                                        onClick=${(
                                                                          /** @type {Event} */ ev,
                                                                        ) => {
                                                                          ev.stopPropagation();
                                                                          openDialog(Settle, {
                                                                            row: r,
                                                                          }).then((x) =>
                                                                            x && reload()
                                                                          );
                                                                        }}>Expired, Assigned or Exercised…</button><button class="btn sm"
                                        onClick=${(/** @type {Event} */ ev) => {
                                          ev.stopPropagation();
                                          openDialog(Mark, { row: r }).then((x) => x && reload());
                                        }}>Type a Mark…</button></div>
                                  `
                                  : null}</div>
                              </td>
                            </tr>
                          `
                          : null}
            `;
          })}</tbody>
        </table>
      </div>
    </div>
  `;
}

/** @param {{ rows: any[] }} p */
function Closed({ rows }) {
  if (!rows.length) return html`<${Empty}>Nothing closed yet</${Empty}>`;
  const total = Dec.sum(rows.map((r) => dec(r.realized)));
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only">Closing trades</caption>
          <thead>
            <tr>
              <th>Instrument</th>
              <th>Account</th>
              <th>Opened</th>
              <th>Closed</th>
              <th>How</th>
              <th class="num">Proceeds</th>
              <th class="num">Cost</th>
              <th class="num">Realized</th>
              <th>Term</th>
            </tr>
          </thead>
          <tbody>${rows.map((r) =>
            html`
              <tr>
                <td><b>${symbol(r.symbol)}</b> <span class="small dim">${quantity(
                  r.quantity,
                )}</span></td>
                <td class="small dim">${r.accountName}</td>
                <td class="small dim">${date(r.opened)}</td>
                <td class="small dim">${date(r.closed)}</td>
                <td class="small">${r.how}</td>
                <td class="num">
                  <${Amt} v=${r.proceeds} />
                </td>
                <td class="num">${r.cost
                  ? html`<${Amt} v=${r.cost} />`
                  : html`<span class="pill warn">missing</span>`}</td>
                <td class="num">${r.realized ? html`<${Amt} v=${r.realized} signed />` : '—'}${num(
                    r.washDisallowed,
                  )
                  ? html`
                    <div class="small"><span class="pill warn" title="Wash sale">W</span> <${Amt}
                        v=${r.washDisallowed} /> disallowed</div>
                  `
                  : null}</td>
                <td class="small">${TERM[r.term]}</td>
              </tr>
            `
          )}</tbody>
          <tfoot>
            <tr>
              <td colspan="7">Realized, all shown</td>
              <td class="num">
                <${Amt}
                  v=${String(total)} signed />
              </td>
              <td></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  `;
}

function Trades() {
  const res = useList('/positions/option-trades', {}, ['import', 'prices']);
  const rows = /** @type {any[]} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!rows) return html`<${Loading} lines=${4} />`;
  if (!rows.length) return html`<${Empty}>No option trades yet</${Empty}>`;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only">Option trades</caption>
          <thead>
            <tr>
              <th>Contract</th>
              <th>Account</th>
              <th>Opened</th>
              <th>Closed</th>
              <th class="num">Premium In</th>
              <th class="num">Premium Out</th>
              <th class="num">P/L</th>
              <th class="num" data-help="capital-required">Capital Required</th>
              <th class="num" data-help="capital-required">Return on It</th>
            </tr>
          </thead>
          <tbody>${rows.map((r) =>
            html`
              <tr>
                <td><b>${symbol(r.symbol)}</b> <span class=${'pill ' +
                  (r.side === 'short' ? 'warn' : '')}>${r
                    .side === 'short'
                  ? 'Short'
                  : 'Long'}</span> <span class="small dim">×${quantity(r.contracts)}</span>${r
                    .adjustedFrom
                  ? html`<div class="small dim">adjusted ${date(r.adjustedOn)} from ${
                    symbol(r.adjustedFrom)
                  }</div>`
                  : null}</td>
                <td class="small dim">${r.accountName}</td>
                <td class="small dim">${date(r.opened)}</td>
                <td class="small">${r.closed
                  ? html`<span class="dim">${date(r.closed)}</span> ${r.how}`
                  : html`<span class="pill">open</span>`}</td>
                <td class="num">
                  <${Amt} v=${r.premiumIn} />
                </td>
                <td class="num">
                  <${Amt} v=${r.premiumOut} />
                </td>
                <td class="num">${r.pl ? html`<${Amt} v=${r.pl} signed />` : '—'}${r.closed
                  ? null
                  : html`<div class="small dim">if closed now</div>`}</td>
                <td class="num">
                  <${Amt} v=${r.capitalRequired} cents=${false} />
                </td>
                <td class="num">${r.returnPct != null ? `${r.returnPct}%` : '—'}</td>
              </tr>
            `
          )}</tbody>
        </table>
      </div>
    </div>
  `;
}

/** Why a gain has no term (S3.1), and how to give it one. */
const UNKNOWN_TERM =
  'Lots whose day bought is missing, so their term isn’t known: type each lot’s day bought on the shares moved in.';

/** How to count a lot left out of the unrealized gains (S3.9). */
const NO_BASIS = 'Their gain isn’t known: add each lot’s cost basis on the shares moved in.';

/**
 * The trade that closes an open option (S3.2): its contract itself, which an adjusted one
 * (its own root, S3.10.2) needs; buy to close a short one, sell to close a long one; all its
 * contracts.
 * @param {any} r
 */
function closing(r) {
  return {
    symbol: r.symbol,
    instrumentId: r.instrumentId,
    action: r.side === 'short' ? 'buy-to-close' : 'sell-to-close',
    // As a person types it: "2", not the API's "2.0".
    contracts: String(dec(r.quantity).abs()).replace(/\.0*$|(\.\d*?)0+$/, '$1'),
  };
}

function Gains() {
  const fmt = useFormats();
  const now = fmt.thisYear();
  const [by, setBy] = useState('year');
  const [year, setYear] = useState('');
  const res = useApi('/positions/gains', { by, year: year || undefined }, ['import', 'prices']);
  const v = /** @type {any} */ (res.data);
  /** @param {any[]} rows @param {string} title @param {any} [after] */
  const table = (rows, title, after = null) => {
    // A lot whose day bought is missing has no term (S3.1): its own column, only then (S3.9).
    const unknown = rows.some((g) => g.unknownTerm != null);
    return html`
      <div class="card"
        style=${{ padding: '4px 8px' }}><h3 style=${{
          padding: '8px 8px 0',
        }}>${title}</h3>${rows.length
          ? html`
            <div class="table-wrap">
              <table class="t">
                <caption class="sr-only">${title}</caption>
                <thead>
                  <tr>
                    <th></th>
                    <th class="num">Short Term</th>
                    <th class="num">Long Term</th>
                    ${unknown
                      ? html`<th class="num" data-tip=${UNKNOWN_TERM} aria-description=${UNKNOWN_TERM}>
                        Unknown Term</th>`
                      : null}
                    <th class="num">Total</th>
                  </tr>
                </thead>
                <tbody>${rows.map((g) =>
                  html`
                    <tr>
                      <td>${g.label}</td>
                      <td class="num">
                        <${Amt} v=${g.shortTerm} signed />
                      </td>
                      <td class="num">
                        <${Amt} v=${g.longTerm} signed />
                      </td>
                      ${unknown
                        ? html`<td class="num">${
                          g.unknownTerm != null ? html`<${Amt} v=${g.unknownTerm} signed />` : ''
                        }</td>`
                        : null}
                      <td class="num"><b><${Amt}
                                  v=${g.total} signed /></b></td>
                    </tr>
                  `
                )}</tbody>
              </table>
            </div>
          `
          : html`<p class="small dim">None.</p>`}${after}</div>
    `;
  };
  // Lots without a cost basis have no gain to count (S3.9): named under the table, grouped
  // as it is: "MSFT (2 lots)" by instrument, "IRA: MSFT (1 lot); Joint: …" by account.
  const lotsOf = (/** @type {any} */ x) =>
    `${symbol(x.symbol)} (${x.lots} lot${x.lots === 1 ? '' : 's'})`;
  /** @type {Map<string, string[]>} */
  const byAccount = new Map();
  for (const x of v?.leftOut || []) {
    const k = x.accountName ?? '';
    byAccount.set(k, [...(byAccount.get(k) || []), lotsOf(x)]);
  }
  const named = [...byAccount].map(([acct, xs]) => (acct ? `${acct}: ` : '') + xs.join(', '))
    .join('; ');
  const leftOut = named
    ? html`
      <p class="small dim" style=${{ padding: '0 8px' }} data-tip=${NO_BASIS}
        aria-description=${NO_BASIS}>Left out, no cost basis: ${named}</p>
    `
    : null;
  return html`
    <div
      class="toolbar"><${Chips} label="By" value=${by} onChange=${setBy} options=${[
        ['year', 'Year'],
        ['month', 'Month'],
        ['account', 'Account'],
        ['instrument', 'Instrument'],
        ['term', 'Term'],
      ]} /><span class="spacer"></span><${Chips} label="Year" value=${year} onChange=${setYear}
      options=${[
        ['', 'All years'],
        ...[now - 2, now - 1, now].map((y) => [String(y), String(y)]),
      ]} /></div>
    ${res.error ? html`<${Failed} error=${res.error} />` : !v ? html`<${Loading} />` : html`
      <div class=${v.unrealized.some((/** @type {any} */ g) => g.unknownTerm != null)
        ? 'grid' // a fourth figure's column needs the width: one table above the other
        : 'grid g2'}>${table(v.realized, 'Realized')}${table(
          v.unrealized,
          by === 'instrument' ? 'Unrealized, by instrument' : 'Unrealized, by account',
          leftOut,
        )}</div>
    `}
  `;
}
