// A portfolio's page (requirements S5.2): Performance (value over time with contributions apart
// from growth, against its benchmark; time- and money-weighted returns) and Holdings.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { PlansFor } from '../components/plans.js';
import { useApi, useList } from '../app/hooks.js';
import { bitcoin, date, quantity } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';
import { Amt, Pct } from '../components/amount.js';
import { Chips, Empty, Failed, Loading, Tabs, Tile } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { openDialog } from '../components/dialog.js';
import { ShareDialog } from '../components/share.js';
import { RANGES, TimeChart } from '../charts/chart.js';
import { BENCHMARKS, PortfolioDialog } from './portfolio-dialog.js';

const TABS = /** @type {[string, string][]} */ ([
  ['performance', 'Performance'],
  ['holdings', 'Holdings'],
  ['projections', 'Projections'],
]);

/** @param {{ id: string, tab?: string }} p */
export default function Portfolio({ id, tab }) {
  const current = tab === 'holdings' || tab === 'projections' ? tab : 'performance';
  const res = useApi(`/portfolios/${id}`, {}, ['share']);
  const p = /** @type {any} */ (res.data);
  useTitle(p ? p.name : 'Portfolio', [['Portfolios', '/ui/portfolios']]);
  useGuide('portfolio-' + current);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!p) return html`<${Loading} lines=${6} />`;
  return html`
    <div
      class="toolbar"><${Tile} group="investing" icon="pie" /><b style=${{ fontSize: '16px' }}>${p
        .name}</b>
        ${!p.access.mine
          ? html`<span class="pill">${p.ownerName} · ${p.access.writable ? 'write' : 'read'}</span>`
          : null}<span class="spacer"></span>
        ${p.access.shareable && !p.implicit
          ? html`
            <button type="button" class="btn" onClick=${() =>
              openDialog(ShareDialog, { kind: 'portfolio', id: p.id, name: p.name }).then(
                res.reload,
              )}>
              <${Icon} name="share" /> Share</button>
          `
          : null}
        ${p.access.writable && !p.implicit
          ? html`
            <button type="button" class="btn"
              onClick=${() =>
                openDialog(PortfolioDialog, { portfolio: p }).then((x) =>
                  x && res.reload()
                )}>Edit</button>
          `
          : null}</div>
        <${Tabs} tabs=${TABS} current=${current} base=${`/ui/portfolios/${p.id}`} />
        ${current === 'performance'
          ? html`<${Performance} p=${p} />`
          : current === 'projections'
          ? html`<${PlansFor} kind="portfolio" id=${p.id} all=${true} />`
          : html`<${Holdings} p=${p} />`}
  `;
}

/** @param {{ p: any }} props */
function Performance({ p }) {
  const [range, setRange] = useState('1Y');
  const series = useApi(`/portfolios/${p.id}/series`, { metric: 'value', range }, [
    'prices',
    'import',
  ]);
  const returns = useList(`/portfolios/${p.id}/returns`, {}, ['prices', 'import']);
  const s = /** @type {any} */ (series.data);
  const rows = /** @type {any[]} */ (returns.data);
  const bench = BENCHMARKS.find(([k]) => k === p.benchmark)?.[1] || p.benchmark;
  return html`
    <div class="grid g4">
      <div class="card kpi">
        <div class="label">Value</div>
        <div class="value">
          <${Amt} v=${s?.end ?? p.value} cents=${false} />
        </div>
        <div class="delta dim">${p.accountIds.length} account${p.accountIds.length === 1
          ? ''
          : 's'}</div>
      </div>
      <div class="card kpi" data-help="time-weighted-return">
        <div class="label">Time-weighted return (${range})</div>
        <div class="value">${s ? html`<${Pct} v=${s.twr} />` : '…'}</div>
        <div class="delta dim">what the investments did</div>
      </div>
      <div class="card kpi" data-help="money-weighted-return">
        <div class="label">Money-weighted (IRR)</div>
        <div class="value">${s ? html`<${Pct} v=${s.irr} />` : '…'}</div>
        <div class="delta dim">a year, for your timing</div>
      </div>
      <div class="card kpi">
        <div class="label">Contributed (${range})</div>
        <div class="value">${s ? html`<${Amt} v=${s.contributed} cents=${false} />` : '…'}</div>
        <div class="delta dim">${s
          ? html`growth <${Amt} v=${s.growth} signed cents=${false} />`
          : ''}</div>
      </div>
    </div>
    <div
      class="card mt"><h3>Value over time<span class="spacer"></span><${Chips} label="Range" value=${range} onChange=${setRange} options=${RANGES} /></h3>
      ${series.error
        ? html`<${Failed} error=${series.error} />`
        : s
        ? html`<${TimeChart} tall label=${`${p.name}: value, net contributions and benchmark`} series=${[
          {
            name: p.name,
            color: '--accent',
            area: true,
            points: s.points.map((/** @type {any} */ x) => [x.date, x.value]),
          },
          {
            name: `Benchmark: ${bench}`,
            color: '--c3',
            dash: true,
            points: s.points.filter((/** @type {any} */ x) => x.benchmark != null)
              .map((/** @type {any} */ x) => [x.date, x.benchmark]),
          },
          {
            name: 'Net contributions',
            color: '--fg-muted',
            points: s.points.map((/** @type {any} */ x) => [x.date, x.contributions]),
          },
        ]} />`
        : html`<${Loading} lines=${4} />`}
      <p class="small dim">The benchmark is given the same money at the same times, so the lines compare what the
        investments did, not when money came in.</p></div>
    <div class="card mt"><h3>Returns by period</h3>
      ${!rows ? html`<${Loading} />` : html`
        <div class="table-wrap">
          <table class="t">
            <caption class="sr-only">Time-weighted returns by period</caption>
            <thead>
              <tr>
                <th>Account</th>
                <th class="num">1M</th>
                <th class="num">3M</th>
                <th class="num">YTD</th>
                <th class="num">1Y</th>
                <th class="num">3Y (a year)</th>
                <th class="num">5Y (a year)</th>
              </tr>
            </thead>
            <tbody>${rows.map((r, i) =>
              html`<tr style=${
                i === rows.length - 1 ? { fontWeight: 600 } : undefined
              }><td>${r.name}</td>
          ${
                ['1M', '3M', 'YTD', '1Y', '3Y', '5Y'].map((k) =>
                  html`
                    <td class="num">
                      <${Pct} v=${r.periods[k]} />
                    </td>
                  `
                )
              }</tr>`
            )}</tbody>
          </table>
        </div>
      `}</div>
  `;
}

/** @param {{ p: any }} props */
function Holdings({ p }) {
  const res = useApi(`/portfolios/${p.id}/holdings`, {}, ['prices', 'import']);
  const h = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!h) return html`<${Loading} />`;
  if (!h.holdings.length) return html`<${Empty}>Nothing held in these accounts yet.</${Empty}>`;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only">Holdings</caption>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Name</th>
              <th class="num">Quantity</th>
              <th class="num">Price</th>
              <th class="num">Value</th>
              <th class="num">Cost basis</th>
              <th class="num">Gain</th>
              <th class="num">Weight</th>
            </tr>
          </thead>
          <tbody>${h.holdings.map((/** @type {any} */ x) =>
            html`
              <tr>
                <td><b>${x.symbol}</b>${x.stale
                  ? html`
                    <span class="pill warn">stale</span>
                  `
                  : null}
                    <div class="small dim">${x.accounts.join(', ')}</div></td>
                <td class="dim">${x.name || ''}</td>
                <td class="num">${x.symbol === 'BTC'
                  ? bitcoin(x.quantity)
                  : quantity(x.quantity)}</td>
                <td class="num amt" data-tip=${x.price
                  ? `${x.priceSource === 'close' ? 'Daily close' : x.priceSource} · as of ${
                    date(x.priceAsOf)
                  }`
                  : 'No price yet'}>${x.price ? '$' + quantity(x.price) : '—'}</td>
                <td class="num">
                  <${Amt} v=${x.value} />
                </td>
                <td class="num">${x.costBasis
                  ? html`<${Amt} v=${x.costBasis} />`
                  : html`<span class="pill warn">missing</span>`}</td>
                <td class="num">${x.gain != null ? html`<${Amt} v=${x.gain} signed />` : '—'}</td>
                <td class="num">${x.weight != null ? `${x.weight}%` : '—'}</td>
              </tr>
            `
          )}</tbody>
          <tfoot>
            <tr>
              <td colspan="4">Cash in these accounts</td>
              <td class="num">
                <${Amt} v=${h.cash} />
              </td>
              <td colspan="3"></td>
            </tr>
            <tr>
              <td colspan="4">Total</td>
              <td class="num">
                <${Amt} v=${h.total} />
              </td>
              <td colspan="3"></td>
            </tr>
            ${h.optionsValue != null
              ? html`
                <tr>
                  <td colspan="4" data-help="capital-at-risk">Options · capital at risk</td>
                  <td
                    class="num">
                    <${Amt} v=${h.optionsValue} />
                    <div class="small dim">at risk ${h.capitalAtRiskUnlimited
                      ? 'unlimited'
                      : html`<${Amt} v=${h.capitalAtRisk} />`}</div>
                  </td>
                  <td colspan="3"></td>
                </tr>
              `
              : null}
          </tfoot>
        </table>
      </div>
    </div>
  `;
}
