// The Dashboard (requirements S12.2.1): net worth and its change, the net-worth chart with its
// composition by account group, the accounts by group, and what needs attention.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { useApi, useList } from '../app/hooks.js';
import { ago } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';
import { Amt } from '../components/amount.js';
import { Chips, Failed, GROUP_LABELS, Loading, Tile } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { RANGES, TimeChart } from '../charts/chart.js';
import { openDialog } from '../components/dialog.js';
import { NewAccount } from './new-account.js';
import { num } from '../app/dec.js';

const GROUP_COLORS = /** @type {Record<string, string>} */ ({
  banking: '--hue-banking',
  investing: '--hue-investing',
  retirement: '--hue-retirement',
  education: '--hue-education',
  crypto: '--hue-crypto',
  giving: '--hue-giving',
  liabilities: '--hue-liability',
  'physical-assets': '--hue-other',
});

export default function Dashboard() {
  useTitle('Dashboard');
  useGuide('dashboard');
  const [range, setRange] = useState('1Y');
  const dash = useApi('/dashboard', {}, ['prices', 'import', 'share']);
  const series = useApi('/dashboard/series', { range }, ['prices', 'import', 'share']);
  if (dash.error) return html`<${Failed} error=${dash.error} />`;
  const d = /** @type {any} */ (dash.data);
  if (!d) return html`<${Loading} lines=${6} />`;
  const s = /** @type {any} */ (series.data);
  const labels = /** @type {Record<string, string>} */ (GROUP_LABELS);
  return html`
    <div class="grid g4">
      <div class="card kpi" data-help="net-worth">
        <div class="label">Net worth</div>
        <div class="value">
          <${Amt} v=${d.netWorth} cents=${false} />
        </div>
        <div class="delta"><${Amt} v=${d.change.day} signed /> today · <${Amt} v=${d.change.month}
          signed cents=${false} /> this month · <${Amt} v=${d.change
            .year} signed cents=${false} /> this year</div>
      </div>
      <div class="card kpi">
        <div class="label">Investments</div>
        <div class="value">
          <${Amt} v=${d.investments} cents=${false} />
        </div>
        <div class="delta">${d.investmentsDay != null
          ? html`<${Amt} v=${d.investmentsDay} signed /> today`
          : html`<span class="dim">none yet</span>`}</div>
      </div>
      <div class="card kpi">
        <div class="label">Cash</div>
        <div class="value">
          <${Amt} v=${d.cash} cents=${false} />
        </div>
        <div class="delta dim">${d.cashAccounts} account${d.cashAccounts === 1 ? '' : 's'} ·
          updated ${ago(d.lastUpdated)}</div>
      </div>
      ${d.budget
        ? html`
          <a class="card kpi" href=${`/ui/budgets/${d.budget.id}/month`} data-help="budget">
            <div class="label">${d.budget.name} · ${new Date(d.budget.month + 'T12:00:00')
              .toLocaleDateString('en-US', { month: 'long' })}</div>
            <div class="value">
              <${Amt} v=${d.budget.spent} cents=${false} />
            </div>
            <div class="bar mt" style=${{ marginTop: '8px' }}><i class=${num(d.budget.spent) >
                num(d.budget.plannedSpending)
              ? 'over'
              : ''} style=${{
              width: `${
                Math.min(
                  1,
                  num(d.budget.spent) / Math.max(1, num(d.budget.plannedSpending)),
                ) * 100
              }%`,
            }}></i></div>
            <div class="delta dim">${'of '}<${Amt} v=${d.budget
              .plannedSpending} cents=${false} />${` planned${
              d.budget.daysLeft ? ` · ${d.budget.daysLeft} days left` : ''
            }`}</div>
          </a>
        `
        : html`
          <div class="card kpi">
            <div class="label">Needs attention</div>
            <div class="value">${d.attention.length}</div>
            <div class="delta dim">${d.attention.length ? 'see below' : 'nothing right now'}</div>
          </div>
        `}
    </div>
    <div class="card mt"><h3>Net worth<span class="spacer"></span><${Chips} label="Range"
      value=${range} onChange=${setRange} options=${RANGES} /></h3>
      ${s
        ? html`<${TimeChart} label="Net worth over time, by account group" series=${
          s.groups.map((
            /** @type {string} */ g,
          ) => ({
            name: labels[g] || g,
            color: GROUP_COLORS[g] || '--c8',
            area: true,
            stack: 'groups',
            points: s.points.map((/** @type {any} */ p) => [p.date, p.groups[g]]),
          }))
        } />`
        : html`<${Loading} lines=${4} />`}
    </div>
    <div class="grid g-main mt">
      <div class="card"><h3>Accounts<span class="spacer"></span><button type="button" class="btn sm"
        onClick=${() => openDialog(NewAccount)}><${Icon} name="plus" /> New account</button></h3>
        ${d.groups.length
          ? d.groups.map((/** @type {any} */ g) =>
            html`<a class="list-item" href="/ui/accounts" style=${{ color: 'inherit' }}>
              <${Tile} group=${g.group} /><div class="grow"><b>${labels[g.group] || g.group}</b>
              <div class="small dim">${g.accounts.join(' · ')}</div></div>
              <div class="num"><b><${Amt} v=${g.total} /></b></div></a>`
          )
          : html`<p class="small dim">No accounts yet. Make one, then import its files.</p>`}
      </div>
      <div class="grid" style=${{ alignContent: 'start' }}>
        <${Plans} />
        <div class="card" data-help="needs-attention"><h3>Needs attention</h3>
        ${d.attention.length
          ? d.attention.map((/** @type {any} */ a) =>
            html`
              <div
                class="list-item"><${Icon} name=${a.kind === 'uncategorised'
                  ? 'info'
                  : 'alert'} /><div class="grow small">${a.text}</div><a href=${a
                  .link}>See</a></div>
            `
          )
          : html`<p class="small dim">Nothing needs you right now.</p>`}
      </div>
      </div>
    </div>
  `;
}

const TONE =
  /** @type {Record<string, string>} */ ({ 'on track': 'ok', ahead: 'ok', behind: 'warn' });

/**
 * The active plans (S6.8.1): each with its status, headline and a small chart of the actual
 * balance against the baseline's median.
 */
function Plans() {
  const res = useList('/dashboard/plans', {}, ['import', 'prices', 'share']);
  const rows = /** @type {any[]} */ (res.data);
  if (!rows || !rows.length) return null;
  return html`
    <div class="card" data-help="plans"><h3>Plans<span class="spacer"></span><a class="small"
      href="/ui/projections">Projections</a></h3>
      ${rows.map((p) =>
        html`<a class="list-item" href=${`/ui/projections/${p.id}`} style=${{ color: 'inherit' }}>
          <div class="grow"><b>${p.name}</b> ${
          p.status && p.status !== 'untracked'
            ? html`<span class=${'pill ' + (TONE[p.status] || '')}>${p.status}</span>`
            : null
        }<div class="small dim">${p.headline}${
          p.sharedBy ? ` · shared by ${p.sharedBy}` : ''
        }</div></div>
          <${Spark} actual=${p.actual} baseline=${p.baseline} behind=${
          p.status === 'behind'
        } /></a>`
      )}
    </div>
  `;
}

/**
 * A small line of the actual balance against the baseline's median.
 * @param {{ actual: [string, number][], baseline: [string, number][], behind: boolean }} p
 */
function Spark({ actual, baseline, behind }) {
  const pts = [...actual, ...baseline];
  if (pts.length < 2) return null;
  const t = (/** @type {string} */ d) => new Date(d).getTime();
  const xs = pts.map(([d]) => t(d));
  const ys = pts.map(([, v]) => num(v));
  const [x0, x1] = [Math.min(...xs), Math.max(...xs)];
  const [y0, y1] = [Math.min(...ys), Math.max(...ys)];
  const line = (/** @type {[string, number][]} */ list) =>
    list.map(([d, v]) =>
      `${((t(d) - x0) / (x1 - x0 || 1) * 100).toFixed(1)},${
        (28 - (num(v) - y0) / (y1 - y0 || 1) * 26).toFixed(1)
      }`
    ).join(' ');
  return html`
    <svg width="100" height="30" viewBox="0 0 100 30" aria-hidden="true">
      <polyline points=${line(baseline)} fill="none" stroke="var(--fg-muted)" stroke-dasharray="3 2"
        stroke-width="1" />
      <polyline points=${line(actual)} fill="none" stroke=${behind
        ? 'var(--ask)'
        : 'var(--accent)'} stroke-width="2" />
    </svg>
  `;
}
