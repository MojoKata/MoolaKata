// An account's page (requirements S12.2.2): Overview (its balance chart), Holdings (investing),
// Transactions, Reconcile (banking, card and brokerage, S1.11), Sharing and Settings.
import { useState } from 'preact/hooks';
import { useLocation } from 'preact-iso';
import { html } from '../app/html.js';
import { PlansFor } from '../components/plans.js';
import {
  AnchorRec,
  LoanRec,
  LoanSummary,
  newTerms,
  Schedule,
  TermsCard,
} from '../components/loan.js';
import { Payoff } from '../components/payoff.js';
import { OptionTrade } from '../components/optiontrade.js';
import { Items, ItemsSummary } from '../components/items.js';
import { WalletCard } from '../components/wallet.js';
import { SyncCard } from '../components/connections.js';
import {
  Contributions,
  EduPlanRec,
  Goal,
  loadPlan,
  PlanCard,
  PlanFacts,
  Withdrawals,
} from '../components/edu.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { ago, bitcoin, date, price, quantity, today } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useGuide } from '../components/help.js';
import { Amt } from '../components/amount.js';
import { Chips, Empty, Failed, Loading, Tabs, Tile } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { confirmAction } from '../components/confirm.js';
import { Dialog, openDialog } from '../components/dialog.js';
import { useDialogGuide } from '../components/help.js';
import { errAt, Field, FormError, Input, SwitchRow } from '../components/fields.js';
import { ShareDialog } from '../components/share.js';
import { TxTable } from '../components/txtable.js';
import { toast } from '../components/toast.js';
import { RANGES, TimeChart } from '../charts/chart.js';
import { BY_TYPE } from '../account-types/index.js';
import { ShareMarks } from './accounts.js';
import { ImportDialog } from './import.js';
import { AcctRec, KEPT_BY, KeptBy, LOT_METHODS } from './new-account.js';
import {
  DraftDialog,
  DraftForm,
  RecField,
  saveNow,
  saveOne,
  useDraft,
} from '../components/draft-form.js';
import { TransactionDialog, Txn } from './transaction-dialog.js';
import { Record as Rec } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { offsetOf, Pager } from '../components/pager.js';
import { pageSize } from '../store/prefs.js';
import { Dec, dec } from '../app/dec.js';

/** @param {{ id: string, tab?: string }} p */
export default function Account({ id, tab }) {
  const res = useApi(`/accounts/${id}`, {}, ['import', 'share', 'prices']);
  const accounts = useList('/accounts', {}, ['share']);
  const a = /** @type {any} */ (res.data);
  const type = a ? BY_TYPE[a.type] : null;
  const tabs = !a ? [] : /** @type {[string, string][]} */ ([
    ['overview', 'Overview'],
    ...(type?.loan ? [['schedule', 'Schedule'], ['payoff', 'Payoff']] : []),
    ...(type?.physical ? [['items', 'Items']] : []),
    ...(type?.investing ? [['holdings', 'Holdings']] : []),
    ...(type?.education
      ? [['contributions', 'Contributions'], ['withdrawals', 'Withdrawals'], ['goal', 'Goal']]
      : []),
    ['transactions', 'Transactions'],
    ...(type?.reconcilable ? [['reconcile', 'Reconcile']] : []),
    ['sharing', 'Sharing'],
    ['settings', 'Settings'],
  ]);
  const current = tabs.some(([k]) => k === tab) ? /** @type {string} */ (tab) : 'overview';
  useTitle(a ? a.name : 'Account', [['Accounts', '/ui/accounts']]);
  useGuide('account-' + current, a ? { type: a.type } : undefined);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!a) return html`<${Loading} lines=${6} />`;
  const all = /** @type {any[]} */ (accounts.data) || [a];
  return html`
    <div class="toolbar"><div class="acct-row"><${Tile} group=${a.group} icon=${type?.icon} /><div>
      <div class="name" style=${{ fontSize: '16px' }}>${a.name}</div>
      <div class="sub">${[a.institution, a.typeLabel, a.mask ? '··' + a.mask : null].filter(Boolean)
        .join(' · ')}${a.active ? '' : ' · closed'}</div>
      </div></div><${ShareMarks} a=${a} /><span class="spacer"></span>
      <div style=${{ textAlign: 'right' }}><div style=${{
        fontSize: '22px',
        fontWeight: 650,
      }}><${Amt} v=${a.balance} /></div>
        ${a.change != null
          ? html`<div class="small"><${Amt} v=${a.change} signed /> 30d</div>`
          : null}</div></div>
    <${Tabs} tabs=${tabs} current=${current} base=${`/ui/accounts/${a.id}`} />
    ${current === 'overview' ? html`<${Overview} a=${a} reload=${res.reload} />` : null}
    ${current === 'schedule' ? html`<${Schedule} a=${a} />` : null}
    ${current === 'payoff' ? html`<${Payoff} a=${a} />` : null}
    ${current === 'items' ? html`<${Items} a=${a} />` : null}
    ${current === 'contributions' ? html`<${Contributions} a=${a} />` : null}
    ${current === 'withdrawals' ? html`<${Withdrawals} a=${a} />` : null}
    ${current === 'goal' ? html`<${Goal} a=${a} />` : null}
    ${current === 'holdings' ? html`<${Holdings} a=${a} />` : null}
    ${current === 'transactions' ? html`<${Transactions} a=${a} all=${all} />` : null}
    ${current === 'reconcile'
      ? html`<${Reconcile} a=${a} all=${all} reload=${res.reload} />`
      : null}
    ${current === 'sharing' ? html`<${Sharing} a=${a} reload=${res.reload} />` : null}
    ${current === 'settings' ? html`<${Settings} a=${a} reload=${res.reload} />` : null}
  `;
}

/** @param {{ a: any, reload: () => void }} p */
function Overview({ a, reload }) {
  const [range, setRange] = useState('1Y');
  const series = useApi(`/accounts/${a.id}/series`, { range }, ['import', 'prices']);
  const s = /** @type {any} */ (series.data);
  return html`
    <${PlansFor} kind="account" id=${a.id} />
    ${a.type.startsWith('crypto') && a.level === 'owner'
      ? html`<${BitcoinPairs} a=${a} reload=${reload} />`
      : null}
    <div class="grid g-main">
      <div class="card"><h3>${a.investing
        ? 'Value'
        : 'Balance'}<span class="spacer"></span><${Chips}
          label="Range" value=${range} onChange=${setRange} options=${RANGES} /></h3>
          ${s
            ? html`<${TimeChart} label=${`${a.name} over time`} series=${[{
              name: a.name,
              color: `--hue-${a.group === 'liabilities' ? 'liability' : a.group}`,
              area: true,
              points: s.points.map((/** @type {any} */ p) => [p.date, p.value]),
            }]} />`
            : html`<${Loading} lines=${4} />`}</div>
      ${BY_TYPE[a.type]?.loan
        ? html`
          <div>
            <${LoanSummary} a=${a} reload=${reload} />
          </div>
        `
        : BY_TYPE[a.type]?.physical
        ? html`<${ItemsSummary} a=${a} />`
        : BY_TYPE[a.type]?.education
        ? html`
          <div class="grid" style=${{ alignContent: 'start' }}>
            <${PlanFacts} a=${a} />
            <${Details}
              a=${a} />
          </div>
        `
        : html`<${Details} a=${a} />`}
    </div>
  `;
}

/** @param {{ a: any }} p */
function Details({ a }) {
  const kept = KEPT_BY.find(([k]) => a.keptBy.includes(k))?.[1] || a.keptBy.join(', ');
  return html`
    <div class="card facts"><h3>Details</h3>
        <div class="list-item"><span class="grow dim">Type</span>${a.typeLabel}</div>
        <div class="list-item"><span class="grow dim">Institution</span>${a.institution ||
          '—'}</div>
        <div class="list-item"><span class="grow dim">Kept current by</span>${kept}</div>
        ${a.investing
          ? html`<div class="list-item"><span class="grow dim">Lot method</span>${
            LOT_METHODS.find(([k]) => k === a.lotMethod)?.[1]
          }</div>`
          : null}
        ${a.optionsValue != null
          ? html`<div class="list-item"><span class="grow dim" data-help="capital-at-risk">Options ·
              capital at risk</span><span><${Amt} v=${a.optionsValue} /> · ${
            a.capitalAtRiskUnlimited ? 'unlimited' : html`<${Amt} v=${a.capitalAtRisk} />`
          }</span></div>`
          : null}
        <div class="list-item"><span class="grow dim">Tax treatment</span>${a.tax || '—'}</div>
        <div class="list-item"><span class="grow dim">Opening balance</span><span><${Amt} v=${a
          .openingWorkedOut} />${a.openingStandIn
          ? html`
            <div class="small dim"
              data-tip="Worked out from the earliest balance the institution reported, standing in for history before the first import">stand-in</div>
          `
          : null}</span></div>
        <div class="list-item"><span class="grow dim">Owner</span>${a.ownerName}</div>
        <div class="list-item"><span class="grow dim">Last updated</span>${ago(
          a.lastUpdated,
        )}</div>
      </div>
  `;
}

/** @param {{ a: any }} p */
function Holdings({ a }) {
  const res = useApi(`/accounts/${a.id}/holdings`, {}, ['import', 'prices']);
  const [open, setOpen] = useState(/** @type {string | null} */ (null));
  const h = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!h) return html`<${Loading} />`;
  const trade = a.level !== 'read'
    ? html`
      <div
        class="toolbar"><span class="spacer"></span><button class="btn sm" onClick=${() =>
          openDialog(OptionTrade, { accountId: a.id }).then((x) =>
            x && res.reload()
          )}>Record an option
            trade</button></div>
    `
    : null;
  if (!h.holdings.length) {
    return html`${trade}<${Empty}>Nothing held yet. Import the broker's file, or add a trade.</${Empty}>`;
  }
  return html`
    ${trade}
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
            </tr>
          </thead>
          <tbody>${h.holdings.map((/** @type {any} */ x) =>
            html`
              <tr class="click" onClick=${() =>
                setOpen(open === x.instrumentId ? null : x.instrumentId)}>
                <td><button type="button" class="linklike" aria-expanded=${open === x.instrumentId
                  ? 'true'
                  : 'false'}
                  style=${{ color: 'var(--fg)', fontWeight: 600 }}>${x.symbol}</button></td>
                <td class="dim">${x.name || ''}</td>
                <td class="num">${x.symbol === 'BTC'
                  ? bitcoin(x.quantity)
                  : quantity(x.quantity)}</td>
                <td class="num amt" data-tip=${x.price
                  ? `${
                    x.priceSource === 'close'
                      ? 'Daily close'
                      : x.priceSource === 'statement'
                      ? "The broker's statement value"
                      : x.priceSource === 'manual'
                      ? 'A typed price'
                      : 'The last trade'
                  } · as of ${date(x.priceAsOf)}`
                  : 'No price yet'}>${x.price ? price(x.price) : '—'}</td>
                <td class="num">
                  <${Amt} v=${x.value} />
                </td>
                <td class="num">${x.costBasis
                  ? html`<${Amt} v=${x.costBasis} />`
                  : html`<span class="pill warn">basis missing</span>`}</td>
                <td class="num">${x.gain != null
                  ? html`<${Amt} v=${x.gain} signed />`
                  : html`<span class="dim">—</span>`}</td>
              </tr>
              ${open === x.instrumentId
                ? html`
                  <tr>
                    <td colspan="7">
                      <table class="t">
                        <caption class="sr-only">Lots of ${x.symbol}</caption>
                        <thead>
                          <tr>
                            <th>Acquired</th>
                            <th class="num">Quantity</th>
                            <th class="num">Cost basis</th>
                            <th>Term</th>
                          </tr>
                        </thead>
                        <tbody>${x.lots.map((/** @type {any} */ l) =>
                          html`
                            <tr>
                              <td>${date(l.acquiredOn)}${l.standIn
                                ? html`
                                  <span class="pill"
                                    data-tip="From the broker's positions: earlier history wasn't imported">stand-in</span>
                                `
                                : null}</td>
                              <td class="num">${quantity(l.quantity)}</td>
                              <td class="num">${l.basis
                                ? html`<${Amt} v=${l.basis} />`
                                : html`<span class="pill warn">missing</span>`}</td>
                              <td class="small">${l.longTerm ? 'long term' : 'short term'}</td>
                            </tr>
                          `
                        )}</tbody>
                      </table>
                    </td>
                  </tr>
                `
                : null}
            `
          )}
        </tbody>
          <tfoot>
            <tr>
              <td colspan="4">Cash</td>
              <td class="num">
                <${Amt} v=${h.cash} />
              </td>
              <td colspan="2"></td>
            </tr>
            <tr>
              <td colspan="4">Total</td>
              <td class="num">
                <${Amt} v=${h.total} />
              </td>
              <td colspan="2"></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
      ${h.problems.length
        ? html`
          <div class="notice warn mt">
            <${Icon} name="alert" />
            <div>${h.problems.length} thing${h.problems.length === 1
              ? ''
              : 's'} to check: a sale without a lot, or a position the imported history doesn't explain.</div>
          </div>
        `
        : null}
      <p class="small dim">Prices are daily closes, delayed; hover a price for its source and date.</p>
  `;
}

/** @param {{ a: any, all: any[] }} p */
function Transactions({ a, all }) {
  const [page, setPage] = useState(1);
  const res = useApi('/transactions', {
    account: a.id,
    limit: pageSize.value,
    offset: offsetOf(page),
  }, ['import']);
  const d = /** @type {any} */ (res.data);
  return html`<div class="toolbar"><span class="spacer"></span>
    ${
    a.level !== 'read'
      ? html`
        <button type="button" class="btn" onClick=${() =>
          openDialog(ImportDialog, {
            accounts: all,
            accountId: a.id,
          })}><${Icon} name="upload" /> Import</button>
        <button type="button" class="btn primary"
          onClick=${() =>
            openDialog(TransactionDialog, { accounts: all, accountId: a.id })
              .then((v) => v && res.reload())}><${Icon} name="plus" /> Add</button>
      `
      : null
  }</div>
    ${
    res.error
      ? html`<${Failed} error=${res.error} />`
      : !d
      ? html`<${Loading} />`
      : d.items.length
      ? html`
        <${TxTable} rows=${d.items} showAccount=${false} onChanged=${res.reload} accounts=${all} />
        <${Pager} label="account-tx" shown=${d.items.length} page=${page} total=${d.total}
          onPage=${setPage} />
      `
      : html`<${Empty}>No transactions yet.</${Empty}>`
  }`;
}

/** @param {{ a: any, all: any[], reload: () => void }} p */
function Reconcile({ a, all, reload }) {
  const res = useApi(`/accounts/${a.id}/reconcile`, {}, ['import']);
  const v = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} />`;
  const again = () => {
    res.reload();
    reload();
  };
  const last = v.checks[v.checks.length - 1];
  const bad = last && !last.ok ? last : null;
  const span = v.periods.length ? [v.periods[0].start, v.periods[v.periods.length - 1].end] : null;
  const days = (/** @type {string} */ x, /** @type {string} */ y) =>
    (Date.parse(y) - Date.parse(x)) / 864e5 + 1;
  const segs = [];
  if (span) {
    for (let i = 0; i < v.periods.length; i++) {
      const p = v.periods[i];
      segs.push({ ok: true, from: p.start, to: p.end });
      const g = v.gaps[i];
      if (g) segs.push({ ok: false, from: g[0], to: g[1] });
    }
  }
  return html`
    <div
      class="card"><h3>Coverage<span class="spacer"></span><span class="small dim" style=${{
        fontWeight: 400,
      }}>${span
        ? `what imports cover, ${date(span[0])} to ${date(span[1])}`
        : 'no imports yet'}</span></h3>
      ${segs.length
        ? html`<div class="coverage" role="img" aria-label=${`Covered from ${date(span?.[0])} to ${
          date(span?.[1])
        }, ${v.gaps.length} gap${v.gaps.length === 1 ? '' : 's'}`}>${
          segs.map((s) =>
            html`
              <div class=${s.ok ? 'seg-ok' : 'seg-gap'} style=${{
                flex: String(days(s.from, s.to)),
              }}
                data-tip=${s.ok
                  ? `Covered ${date(s.from)} to ${date(s.to)}`
                  : `Nothing imported between ${date(s.from)} and ${date(s.to)}`}></div>
            `
          )
        }</div>`
        : null}
      ${v.gaps.map((/** @type {string[]} */ g) =>
        html`<div class="list-item mt"><${Icon} name="alert" />
        <div class="grow small"><b>Gap</b>: nothing imported between ${date(g[0])} and ${
          date(g[1])
        }.</div>
        ${
          a.level !== 'read'
            ? html`<button type="button" class="btn sm" onClick=${() =>
              openDialog(ImportDialog, { accounts: all, accountId: a.id }).then(
                again,
              )}>Import a file</button>`
            : null
        }</div>`
      )}
      ${v.overlaps.map((/** @type {string[]} */ o) =>
        html`
          <div class="list-item">
            <${Icon} name="info" />
            <div
              class="grow small"><b>Overlap</b>: two imports both cover ${date(o[0])} to ${date(
                o[1],
              )}. Rows they share were matched, not doubled.</div>
          </div>
        `
      )}
      ${segs.length && !v.gaps.length && !v.overlaps.length
        ? html`<p class="small dim mt" style=${{ marginBottom: 0 }}>No gaps or overlaps.</p>`
        : null}
    </div>
    ${v.needsAnchor
      ? html`
        <div class="notice warn mt">
          <${Icon} name="info" />
          <div>The next statement or import is overdue. Import it, or type today's balance from the institution's site.</div>
        </div>
      `
      : null}
    <div class="card mt"><h3>Balance checks<span class="spacer"></span>${a.level !== 'read'
      ? html`
        <button type="button" class="btn sm" onClick=${() =>
          openDialog(TypeBalance, { a }).then((x) => x && again())}>Type today's balance</button>
        <button type="button" class="btn sm" onClick=${() =>
          openDialog(TickOff, { a }).then((x) =>
            x && again()
          )}>Tick off against a statement</button>
      `
      : null}</h3>
      ${v.checks.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Balances the institution reported, and MoolaKata's</caption>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>From</th>
                  <th class="num">Institution</th>
                  <th class="num">MoolaKata</th>
                  <th>Check</th>
                </tr>
              </thead>
              <tbody>${v.checks.slice(-12).reverse().map((/** @type {any} */ k) =>
                html`
                  <tr>
                    <td>${date(k.date)}</td>
                    <td class="small dim">${{
                      ofx: 'OFX file',
                      'running-balance': 'CSV balance column',
                      statement: 'Statement',
                      typed: 'Typed',
                    }[/** @type {'ofx'} */ (k.source)] || k.source}</td>
                    <td class="num">
                      <${Amt} v=${k.reported} />
                    </td>
                    <td class="num">
                      <${Amt} v=${k.computed} />
                    </td>
                    <td>${k.ok
                      ? html`<span class="pill ok"><${Icon} name="check" /> matches</span>`
                      : html`<span class="pill warn"><${Amt} v=${k.difference} signed /> difference</span>`}</td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        `
        : html`<p class="small dim">No balance from the institution yet.</p>`}
      ${v.openingStandIn
        ? html`
          <p
            class="small dim">The opening balance stands in for history before the first import; it is worked out from the earliest reported balance.</p>
        `
        : null}
    </div>
    ${bad ? html`<${Mismatch} a=${a} check=${bad} all=${all} again=${again} />` : null}
    <${StatementChecks} v=${v} />
    ${v.reconciliations.length
      ? html`<div class="card mt"><h3>Statements ticked off</h3>${
        v.reconciliations.map((/** @type {any} */ r) =>
          html`
            <div
              class="list-item"><div class="grow">${date(
                r.statementDate,
              )}<div class="small dim">statement <${Amt} v=${r.statementBalance} /></div></div>
                    ${r.finishedAt
                      ? html`<span class="pill ok">reconciled</span>`
                      : html`<span class="pill warn"><${Amt} v=${r.difference} signed /> to go</span>`}</div>
          `
        )
      }</div>`
      : null}
  `;
}

/** @param {{ a: any, check: any, all: any[], again: () => void }} p */
function Mismatch({ a, check, all, again }) {
  const s = check.suspects;
  const both = useSubmit(async (/** @type {string} */ id) => {
    await api.post(`/transactions/${id}/both-real`);
    toast('Kept both: remembered');
    again();
  });
  return html`
    <div
      class="card mt"><h3>Mismatch on ${date(
        check.date,
      )}<span class="spacer"></span><span class="pill warn"><${Amt} v=${check
        .difference} signed /></span></h3>
        <p class="small dim" style=${{ marginTop: '-6px' }}>${check.windowFrom
          ? `Between the last match (${date(check.windowFrom)}) and ${date(check.date)}.`
          : `Up to ${date(check.date)}; no earlier balance matched.`}</p>
        ${s.duplicates.map((/** @type {string[]} */ ids) =>
          html`<div class="list-item"><${Icon} name="receipt" />
      <div class="grow"><b>Possible duplicate</b>: ${ids.length} identical rows on one day.</div>
      ${
            a.level !== 'read'
              ? html`
                <button type="button" class="btn sm" onClick=${() =>
                  both.run(ids[0])}>Both are real</button>
                <a class="btn sm" href=${`/ui/accounts/${a.id}/transactions`}>Remove one</a>
              `
              : null
          }</div>`
        )}
        ${s.changed.length
          ? html`
            <div class="list-item">
              <${Icon} name="info" />
              <div
                class="grow"><b>Changed amounts</b>: ${s.changed
                  .length} transaction${s.changed.length === 1
                  ? ''
                  : 's'} changed between imports.</div>
            </div>
          `
          : null}
        ${s.gaps.map((/** @type {string[]} */ g) =>
          html`
            <div
              class="list-item"><${Icon} name="alert" /><div class="grow"><b>Gap</b>: ${date(
                g[0],
              )} to ${date(g[1])} has no imports.</div>
                  ${a.level !== 'read'
                    ? html`<button type="button" class="btn sm" onClick=${() =>
                      openDialog(ImportDialog, { accounts: all, accountId: a.id }).then(
                        again,
                      )}>Import a file</button>`
                    : null}</div>
          `
        )}
        ${s.firstParting
          ? html`
            <div class="list-item">
              <${Icon} name="info" />
              <div
                class="grow small">The file's running balance parts from MoolaKata's at one row; check the transactions around it.</div>
            </div>
          `
          : null}
        ${a.level !== 'read'
          ? html`<div class="toolbar mt"><span class="spacer"></span><button type="button" class="btn sm"
      onClick=${() =>
            openDialog(Adjust, { a, check }).then((x) =>
              x && again()
            )}>Accept as an adjustment…</button></div>`
          : null}
      </div>
  `;
}

/** Whether a receiver counts an account shared with them in their own totals (S10.7). */
class CountedRec extends Rec {
  /** @override */
  static prefix = 'CntAc';
  /** @override */
  static fields = FIELDS.CountedRecord;
}

/** @param {{ close: (v?: any) => void, a: any }} p */
function TypeBalance({ close, a }) {
  useDialogGuide('dialog-type-balance');
  const f = useDraft((draft) => {
    draft.add(AnchorRec, { accountId: a.id, date: today() });
  }, [a.id]);
  const rec = /** @type {AnchorRec | undefined} */ (f.draft?.records[0]);
  return html`
    <${DraftDialog} f=${f} title="Type today's balance" close=${close} what="This balance"
      label="Check" done="Balance recorded and checked">
      <p class="small dim" style=${{ marginTop: 0 }}>Copy the balance from ${a.institution ||
        'the institution'}'s site or app.
          MoolaKata checks it against its own for the same day.</p>
      ${rec
        ? html`
          <div class="row">
            <${RecField} rec=${rec} name="balance" label="Balance" />
            <${RecField} rec=${rec} name="date" label="As of" id="as-of" type="date" />
          </div>
        `
        : null}
    </${DraftDialog}>
  `;
}

/** @param {{ close: (v?: any) => void, a: any, check: any }} p */
function Adjust({ close, a, check }) {
  useDialogGuide('dialog-adjustment');
  // The difference, as a transaction marked an adjustment (S1.11.4): the note says why.
  const f = useDraft((draft) => {
    draft.add(Txn, {
      accountId: a.id,
      date: check.date,
      kind: 'adjustment',
      payee: 'Balance adjustment',
      memo: '',
    }).set('amount', Dec.of(check.difference));
  }, [a.id, check.date]);
  const rec = /** @type {Txn | undefined} */ (f.draft?.records[0]);
  return html`
    <${DraftDialog} f=${f} title="Accept as a balance adjustment" close=${close}
      what="This adjustment" label="Record the adjustment"
      done="Recorded as a balance adjustment">
      <p class="small dim"
        style=${{ marginTop: 0 }}>A transaction of <${Amt} v=${check
          .difference} signed /> on ${date(check.date)},
          marked as an adjustment, in the account and in Activity.</p>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="memo" label="Why" id="note"
            placeholder="A fee the bank refunded" />
        `
        : null}
    </${DraftDialog}>
  `;
}

/** A statement ticked off against (S1.11.6): made by Start, finished by Mark reconciled. */
class ReconRec extends Rec {
  /** @override */
  static prefix = 'Recon';
  /** @override */
  static fields = FIELDS.ReconciliationRecord;
  /** @override */
  static defaults = { finished: false };
}

/** @param {{ close: (v?: any) => void, a: any }} p */
function TickOff({ close, a }) {
  useDialogGuide('dialog-tick-off');
  const [day, setDay] = useState('');
  const [balance, setBalance] = useState('');
  const [rec, setRec] = useState(/** @type {any} */ (null));
  const txns = useApi(rec ? '/transactions' : null, { account: a.id, to: day, limit: 500 });
  const start = useSubmit(async () => {
    const [made] = await saveNow((d) => {
      const r = d.add(ReconRec, { accountId: a.id });
      r.input('statementDate', day);
      r.input('statementBalance', balance);
    });
    setRec(made.record);
  });
  const tick = async (/** @type {any} */ t) => {
    // Each tick saves at once (S1.11.6), through the save every change of a transaction takes.
    await saveNow((d) => d.load(Txn, t).set('cleared', !t.cleared));
    txns.reload();
    const all = await api.get(`/accounts/${a.id}/reconcile`);
    setRec(all.reconciliations.find((/** @type {any} */ r) => r.id === rec.id));
  };
  const finish = useSubmit(async () => {
    await saveNow((d) => d.load(ReconRec, { ...rec, accountId: a.id }).set('finished', true));
    toast('The period is reconciled');
    close(true);
  });
  const rows =
    /** @type {any} */ (txns.data)?.items?.filter((/** @type {any} */ t) => !t.reconciled) || [];
  return html`
    <${Dialog} title="Tick off against a statement" wide close=${close}
      onSubmit=${() => (rec ? finish.run().catch(() => {}) : start.run().catch(() => {}))}
      footer=${html`<button class="btn primary" disabled=${
        start.busy || finish.busy || (rec && !dec(rec.difference).isZero())
      }>${rec ? 'Mark reconciled' : 'Start'}</button>`}>
      <div class="row">
        <${Field} label="Statement closing date" id="statement-date">
          <${Input} type="date" value=${day} onInput=${setDay}
            required disabled=${!!rec} />
          </${Field}>
          <${Field} label="Statement closing balance" id="statement-balance"
            error=${errAt(start.error, 'statementBalance')}><${Input}
            value=${balance} onInput=${setBalance} inputmode="decimal" required disabled=${!!rec} /></${Field}></div>
        ${rec
          ? html`
            <div class="table-wrap" style=${{ maxHeight: '320px', overflow: 'auto' }}>
              <table class="t">
                <caption class="sr-only">Transactions to tick</caption>
                <thead>
                  <tr>
                    <th>Cleared</th>
                    <th>Date</th>
                    <th>Payee</th>
                    <th class="num">Amount</th>
                  </tr>
                </thead>
                <tbody>${rows.map((/** @type {any} */ t) =>
                  html`
                    <tr>
                      <td><input type="checkbox" checked=${t.cleared}
                            aria-label=${'Cleared: ' + (t.payee || '')} onChange=${() =>
                              tick(t)} /></td>
                      <td class="dim">${date(t.date)}</td>
                      <td>${t.payee}</td>
                      <td class="num">
                        <${Amt} v=${t.amount} signed />
                      </td>
                    </tr>
                  `
                )}</tbody>
              </table>
            </div>
            <div class="kv mt">
              <div>
                <div class="k">Cleared balance</div>
                <div class="v">
                  <${Amt} v=${rec.cleared} />
                </div>
              </div>
              <div>
                <div class="k">Statement</div>
                <div class="v">
                  <${Amt} v=${rec.statementBalance} />
                </div>
              </div>
              <div>
                <div class="k">Difference</div>
                <div class="v">
                  <${Amt} v=${rec.difference} signed />
                </div>
              </div>
            </div>
            <p
              class="small dim">Tick until the difference is zero; the period is then marked reconciled, and editing a
                    transaction inside it asks first.</p>
          `
          : null}
        <${FormError} error=${start.error || finish.error} shown=${['statementBalance']} />
      </${Dialog}>
  `;
}

/** @param {{ a: any, reload: () => void }} p */
function Sharing({ a, reload }) {
  const res = useApi(a.level === 'owner' ? `/shares/account/${a.id}` : null, {}, ['share']);
  const v = /** @type {any} */ (res.data);
  if (a.level !== 'owner') {
    return html`
      <div class="card">
        <h3>Shared with you</h3>
        <div class="list-item">
          <div class="grow">
            ${a.ownerName} shares this account with you at <b>${a.level}</b>.${a.level === 'write'
              ? ' You can change what it holds: transactions, imports and categories. Its settings and sharing stay with the owner.'
              : ' You can see everything about it, and change nothing.'}</div>
        </div>
      </div>
    `;
  }
  const holders = v
    ? [
      ...v.users.filter((/** @type {any} */ u) => u.allow !== 'none' || u.via.length).map((
        /** @type {any} */ u,
      ) => ({
        name: u.displayName,
        how: u.allow !== 'none'
          ? 'directly'
          : 'via ' + u.via.map((/** @type {any} */ x) => x.groupName).join(', '),
        allow: u.allow !== 'none' ? u.allow : u.via[0].allow,
      })),
      ...v.groups.filter((/** @type {any} */ g) => g.allow !== 'none').map((
        /** @type {any} */ g,
      ) => ({ name: g.name, how: `group of ${g.members}`, allow: g.allow })),
    ]
    : [];
  return html`
    <div
      class="card"><h3>Who has this account<span class="spacer"></span><button type="button" class="btn sm"
        onClick=${() =>
          openDialog(ShareDialog, { kind: 'account', id: a.id, name: a.name }).then(() => {
            res.reload();
            reload();
          })}><${Icon} name="share" /> Share</button></h3>
        ${!v
          ? html`<${Loading} />`
          : holders.length
          ? holders.map((x) =>
            html`<div class="list-item"><div class="grow">${x.name}
      <div class="small dim">${x.how}</div></div><span class="pill"><${Icon} name=${
              x.allow === 'write' ? 'pencil' : 'eye'
            } /> ${x.allow}</span></div>`
          )
          : html`<p class="small dim">Only you. A new account is shared with no one.</p>`}</div>
  `;
}

/**
 * The account's Settings (S12.2.2): its own fields, and a loan's terms, in one form (S12.15),
 * with a wallet's keys or a 529's plan beside it.
 * @param {{ a: any, reload: () => void }} p
 */
function Settings({ a, reload }) {
  const { route } = useLocation();
  const owner = a.level === 'owner';
  const loan = BY_TYPE[a.type]?.loan;
  const physical = BY_TYPE[a.type]?.physical;
  const wallet = BY_TYPE[a.type]?.wallet;
  const education = BY_TYPE[a.type]?.education;
  const f = useDraft(async (draft) => {
    draft.load(AcctRec, await api.get(`/accounts/${a.id}`));
    if (education) await loadPlan(draft, a.id);
    if (!loan) return;
    // The loan's terms, saved with the account's settings; made once typed in (S1.9).
    const terms = (await api.get(`/accounts/${a.id}/loan`)).terms;
    if (terms) draft.load(LoanRec, { ...terms, accountId: a.id });
    else draft.add(LoanRec, newTerms(a.type, a.id), { optional: true });
  }, [a.id]);
  // A receiver's Count in my totals: a record of their own (S10.7).
  const counted = useSubmit(async (/** @type {boolean} */ v) => {
    const row = a.countedId
      ? { id: a.countedId, version: a.countedVersion, accountId: a.id, counted: a.counted }
      : null;
    await saveOne(CountedRec, row, { accountId: a.id, counted: v });
    toast(v ? 'Counted in your totals' : 'Left out of your totals');
    reload();
  });
  if (!owner) {
    return html`
      <div class="card content-narrow">
        <h3>Your view of it</h3>
        <${SwitchRow} label="Count in my totals"
          hint="Off by default: a shared account counts in your net worth only if you say so."
          on=${a.counted} onChange=${(/** @type {boolean} */ v) => counted.run(v)} />
      </div>
    `;
  }
  const rec = /** @type {AcctRec | undefined} */ (f.draft?.records[0]);
  const terms = /** @type {LoanRec | undefined} */ (
    f.draft?.records.find((r) => r instanceof LoanRec)
  );
  const plan = /** @type {EduPlanRec | undefined} */ (
    f.draft?.records.find((r) => r instanceof EduPlanRec)
  );
  /** How it is kept current, for the types kept from files or statements. */
  const keeping = (/** @type {AcctRec} */ r) =>
    html`
      <${KeptBy} rec=${r} label="Method" />
      <${SyncCard} rec=${r} />
      <${StatementsExpected} a=${a} rec=${r} />
    `;
  return html`
    <${DraftForm} f=${f} where="the account's settings" what="This account" done="Saved"
      saved=${() => {
        toast('Saved');
        f.reload();
        reload();
      }}
      extra=${({ save }) =>
        html`
          <button type="button" class="btn danger" disabled=${save.busy}
            onClick=${async () => {
              if (!rec || !f.draft) return;
              if (!(await confirmAction({ title: `Delete ${a.name}?` }))) return;
              f.draft.remove(rec);
              const r = await save.run().catch(() => null);
              if (r?.status === 'saved') {
                toast(`${a.name} deleted`);
                route('/ui/accounts');
              } else if (r?.status !== 'asks') f.draft.unremove(rec);
            }}>Delete account…</button>
        `}>
      ${rec
        ? html`
          <div class="grid g2">
            <div class="card">
              <h3>Account</h3>
              <${RecField} rec=${rec} name="name" label="Name" />
              <div class="row">
                <${RecField} rec=${rec} name="institution" label="Institution" />
                <${RecField} rec=${rec} name="mask" label="Last 4" id="mask" />
              </div>
              ${a.investing
                ? html`
                  <${RecField} rec=${rec} name="lotMethod" label="Lot method"
                    options=${LOT_METHODS}
                    hint="How sales pick lots. The method in force at a sale is recorded with it." />
                `
                : null}
              ${loan || physical || wallet ? null : html`
                <div class="row">
                  <${RecField} rec=${rec} name="openingBalance" label="Opening balance" />
                  <${RecField} rec=${rec} name="openingDate" label="Opening balance date"
                    id="opening-date" type="date" />
                </div>
              `}
              <${RecField} rec=${rec} name="active" label="Active"
                hint="A closed account stays for history and taxes." />
              <${RecField} rec=${rec} name="countInNetWorth" label="Count in net worth"
                hint="Your totals include it." />
            </div>
            ${loan && terms
              ? html`
                <div class="grid" style=${{ alignContent: 'start' }}>
                  <${TermsCard} a=${a} rec=${terms} />
                  <div class="card">
                    <h3>Statements</h3>
                    <${StatementsExpected} a=${a} rec=${rec} />
                  </div>
                </div>
              `
              : wallet
              ? html`<${WalletCard} a=${a} rec=${rec} />`
              : physical
              ? html`
                <div class="card">
                  <h3>Keeping it current</h3>
                  <p class="small dim">Its value is its items': add them, and their valuations,
                    on the Items tab.</p>
                </div>
              `
              : education && plan && f.draft
              ? html`
                <div class="grid" style=${{ alignContent: 'start' }}>
                  <${PlanCard} rec=${plan} draft=${f.draft} />
                  <div class="card">
                    <h3>Keeping it current</h3>
                    ${keeping(rec)}
                  </div>
                </div>
              `
              : html`
                <div class="card">
                  <h3>Keeping it current</h3>
                  ${keeping(rec)}
                  ${education
                    ? null
                    : html`<p class="small dim">Import OFX, QFX or CSV files from the Transactions
                      tab. A CSV's columns are asked once per institution and remembered.</p>`}
                  ${['savings', 'money-market'].includes(a.type)
                    ? html`
                      <${RecField} rec=${rec} name="withdrawalsAMonth"
                        label="Withdrawals allowed a month" id="withdrawals-a-month"
                        placeholder="no limit"
                        hint="The bank's limit, empty for none. Budgets sum the moves back within it." />
                    `
                    : null}
                </div>
              `}
          </div>
        `
        : null}
    </${DraftForm}>
  `;
}

const INTERVALS = /** @type {[string, string][]} */ ([
  ['monthly', 'Monthly'],
  ['quarterly', 'Quarterly'],
  ['yearly', 'Yearly'],
  ['none', 'None'],
]);

/**
 * How often the institution issues statements (S1.11.7): an overdue one raises an alert. Set
 * here or following the account's type; one learned from what arrives is proposed, to use or
 * set aside with the form's Save.
 * @param {{ a: any, rec: AcctRec }} p
 */
function StatementsExpected({ a, rec }) {
  const label = (/** @type {string} */ k) => INTERVALS.find(([x]) => x === k)?.[1] || k;
  const p = a.statementIntervalProposal;
  return html`
    <${RecField} rec=${rec} name="statementInterval" label="Statements expected"
      id="statements-expected"
      hint="An alert asks for a statement once it is overdue: the interval and a grace period after it."
      options=${[
        ['', `As the type: ${label(a.statementIntervalDefault).toLowerCase()}`],
        ...INTERVALS,
      ]} />
    ${p && rec.get('statementInterval') !== p && rec.get('statementIntervalDismissed') !== p
      ? html`
        <div class="notice" role="status">
          <${Icon} name="info" />
          <div>Statements seem to arrive ${label(p).toLowerCase()}. <button type="button"
              class="btn sm" onClick=${() => rec.set('statementInterval', p)}>Use ${label(p)
                .toLowerCase()}</button> <button type="button" class="btn sm"
              onClick=${() => rec.set('statementIntervalDismissed', p)}>Dismiss</button></div>
        </div>
      `
      : null}
  `;
}

/**
 * A brokerage statement's checks (S1.3.3.8): its ending values against what the account was
 * worth those days, and its latest positions against what is held.
 * @param {{ v: any }} p
 */
function StatementChecks({ v }) {
  if (!v.valueChecks.length && !v.holdingChecks.length) return null;
  return html`
    <div class="grid g2 mt">
      ${v.valueChecks.length
        ? html`
          <div
            class="card"><h3 data-help="value-checks">Statement values</h3>${v.valueChecks
              .slice(-6)
              .reverse()
              .map((/** @type {any} */ c) =>
                html`<div class="list-item"><div class="grow">${date(c.date)}<div class="small dim"
              >statement <${Amt} v=${c.reported} /> · MoolaKata <${Amt} v=${c.computed} /></div
              ></div>${
                  c.ok
                    ? html`<span class="pill ok">matches</span>`
                    : html`<span class="pill warn"><${Amt} v=${c.difference} signed /></span>`
                }</div>`
              )}<p class="small dim">Cash and holdings together, at that day's prices: within half a
                      percent counts as a match.</p></div>
        `
        : null}
      ${v.holdingChecks.length
        ? html`<div class="card"><h3 data-help="holdings-check">Holdings on ${
          date(
            v.holdingChecksAsOf,
          )
        }</h3>${
          v.holdingChecks.map((/** @type {any} */ h) =>
            html`<div class="list-item"><div class="grow">${
              h.symbol || h.label
            }<div class="small dim"
            >statement ${h.statement ?? '—'} · MoolaKata ${h.held ?? 'not held'}${
              h
                  .statementBasis != null
                ? html`
                  · basis on the statement <${Amt} v=${h.statementBasis} />
                `
                : null
            }</div></div>${
              h.difference == null
                ? html`<span class="pill">not matched</span>`
                : h.ok
                ? html`<span class="pill ok">matches</span>`
                : html`<span class="pill warn">${String(h.difference).replace('-', '')} ${
                  dec(h.difference).sign() > 0 ? 'short' : 'over'
                }</span>`
            }</div>`
          )
        }</div>`
        : null}
    </div>
  `;
}

/**
 * Bitcoin moved between the owner's accounts, proposed as pairs (S1.7.1): confirmed, the coins
 * arrive with the lots they left with.
 * @param {{ a: any, reload: () => void }} p
 */
function BitcoinPairs({ a, reload }) {
  const res = useList('/transfers/bitcoin', {}, ['import']);
  const rows = /** @type {any[]} */ (res.data || []).filter((x) =>
    x.fromAccount === a.name || x.toAccount === a.name
  );
  const act = useSubmit(async (/** @type {any} */ x, /** @type {boolean} */ confirm) => {
    await api.post(`/transfers/bitcoin/${x.id}`, { confirm }, { version: x.version });
    toast(confirm ? 'Matched: the coins carry their lots' : 'Not a transfer between your accounts');
    res.reload();
    reload();
  });
  return html`${
    rows.map((x) =>
      html`
        <div class="notice mb" role="status">
          <${Icon} name="info" />
          <div><b>${bitcoin(
            x.sats,
            true,
          )}</b> left ${x.fromAccount} on ${date(x.fromDate)} and arrived in ${x
            .toAccount} on ${date(
              x.toDate,
            )}: one transfer? <button type="button" class="btn sm primary" disabled=${act.busy}
              onClick=${() =>
                act.run(x, true).catch(() => {})}>Match them</button> <button type="button"
              class="btn sm" disabled=${act.busy} onClick=${() =>
                act.run(x, false).catch(() => {})}>Not a transfer</button></div>
        </div>
      `
    )
  }`;
}
