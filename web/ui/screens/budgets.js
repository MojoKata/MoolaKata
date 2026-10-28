// Budgets (requirements S7.1–S7.5): a month's categories as progress bars, income against
// spending, cash flow, a category's trend, and the recurring transactions, for one budget at a
// time. A household budget is one shared with a group at write.
import { signal } from '@preact/signals';
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date, money, today } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useDialogGuide, useGuide } from '../components/help.js';
import { Empty, Failed, Loading, Tabs } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { Dialog, openDialog } from '../components/dialog.js';
import { errAt, Field, FormError, Input, Select, Switch, SwitchRow } from '../components/fields.js';
import { toast } from '../components/toast.js';
import { ShareDialog } from '../components/share.js';
import { BarChart, FlowChart } from '../charts/chart.js';
import { Dec, dec, num } from '../app/dec.js';
import { Draft, Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { TransactionDialog } from './transaction-dialog.js';
import { changes } from '../app/stream.js';
import { Amt } from '../components/amount.js';

const TABS = /** @type {[string, string][]} */ ([
  ['month', 'Month'],
  ['cash-flow', 'Cash flow'],
  ['trends', 'Trends'],
  ['recurring', 'Recurring'],
  ['reimbursements', 'Reimbursements'],
]);
TABS.splice(1, 0, ['where', 'Where it is']);
TABS.unshift(['list', 'Budgets']);
TABS.splice(TABS.length - 1, 0, ['compare', 'Compare']);
TABS.splice(3, 0, ['review', 'Review']);

/** The month shown, kept while moving between tabs and budgets. */
const shown = signal('');

/** @param {Date} d */
function monthKey(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
}

/** @param {string} key */
function monthLabel(key) {
  const [y, m] = key.split('-').map(Number);
  return new Date(y, m - 1, 1).toLocaleDateString('en-US', { month: 'long', year: 'numeric' });
}

/** @param {{ id?: string, tab?: string }} p */
export default function Budgets({ id, tab }) {
  useTitle('Budgets');
  const current = TABS.some(([k]) => k === tab) ? /** @type {string} */ (tab) : 'month';
  useGuide('budgets-' + current);
  const list = useList('/budgets', {}, ['share']);
  const budgets = /** @type {any[]} */ (list.data);
  if (list.error) return html`<${Failed} error=${list.error} />`;
  if (!budgets) return html`<${Loading} lines=${6} />`;
  const [y, m] = today().split('-').map(Number);
  const now = new Date(y, m - 1, 1);
  if (!shown.value) shown.value = monthKey(now);
  const months = Array.from(
    { length: 13 },
    (_, i) => monthKey(new Date(now.getFullYear(), now.getMonth() + 1 - i, 1)),
  );
  const newBudget = () =>
    openDialog(BudgetDialog, {}).then(async (b) => {
      if (!b) return;
      // A plan from history first, when chosen (S7.1.5); the budget is made either way.
      if (b.estimate) {
        await openDialog(EstimateDialog, { b, month: monthKey(now), months: b.estimate });
      }
      list.reload();
      location.assign(`/ui/budgets/${b.id}/month`);
    });
  if (!budgets.length) {
    return html`
      <${Empty}>No budget yet. A budget plans spending per category over the accounts you
        choose; share it with a group at write for a household budget.
        <div class="mt"><button type="button" class="btn primary" onClick=${newBudget}>
          <${Icon} name="plus" /> New budget</button></div></${Empty}>
    `;
  }
  const b = budgets.find((x) => x.id === id) || budgets[0];
  return html`
    <div class="toolbar">
      <select class="in" style=${{ maxWidth: '180px' }} aria-label="Month" id="f-month"
        value=${shown.value} onChange=${(
          /** @type {any} */ e,
        ) => (shown.value = e.currentTarget.value)}>
        ${months.map((m) => html`<option value=${m}>${monthLabel(m)}</option>`)}
      </select>
      <select class="in" style=${{ maxWidth: '220px' }} aria-label="Budget" id="f-budget"
        value=${b.id} onChange=${(/** @type {any} */ e) =>
          location.assign(`/ui/budgets/${e.currentTarget.value}/${current}`)}>
        ${budgets.map((x) =>
          html`<option value=${x.id}>${x.name}${x.level === 'owner' ? '' : ` (${x.ownerName})`}${
            x.active ? ' (active)' : ''
          }</option>`
        )}
      </select>
      <button type="button" class="icon-btn" title="Refresh: work the month out again"
        aria-label="Refresh" data-help="refresh"
        onClick=${async () => {
          await api.post(`/budgets/${b.id}/refresh`, {}, { params: { month: shown.value } });
          changes.value = { ...changes.value, refresh: (changes.value.refresh || 0) + 1 };
          toast('Worked out again');
        }}><${Icon} name="refresh" /></button>
      <span class="spacer"></span>
      <button type="button" class="btn"
        onClick=${newBudget}><${Icon} name="plus" /> New budget</button>
    </div>
    ${!b.active
      ? html`
        <div class="notice warn" style=${{ marginBottom: '12px' }}>
          <${Icon} name="info" />
          <div class="grow"><b>Scenario:</b> not the budget you follow. ${b.method === 'envelope'
            ? 'An envelope'
            : 'A tracking'} budget.</div>
          <button type="button" class="btn sm" onClick=${() =>
            openDialog(MakeActiveDialog, { b, from: budgets.find((x) => x.active) }).then((x) =>
              x && list.reload()
            )}>Make active</button>
          <a class="btn sm" href=${`/ui/budgets/${b.id}/compare`}>Compare</a>
        </div>
      `
      : null}
    <${Tabs} tabs=${TABS} current=${current} base=${`/ui/budgets/${b.id}`} />
    ${current === 'month'
      ? html`<${ThisMonth} b=${b} month=${shown.value} reloadList=${list.reload} />`
      : current === 'cash-flow'
      ? html`<${CashFlow} b=${b} month=${shown.value} />`
      : current === 'trends'
      ? html`<${Trends} b=${b} month=${shown.value} />`
      : current === 'reimbursements'
      ? html`<${Reimbursements} b=${b} />`
      : current === 'list'
      ? html`<${BudgetList} budgets=${budgets} reload=${list.reload} />`
      : current === 'review'
      ? html`<${Review} b=${b} />`
      : current === 'compare'
      ? html`<${Compare} b=${b} budgets=${budgets} month=${shown.value} />`
      : current === 'where'
      ? html`<${WhereMoneyIs} b=${b} month=${shown.value} />`
      : html`<${Recurring} b=${b} />`}
  `;
}

/** @param {{ b: any, month: string, reloadList: () => void }} p */
function ThisMonth({ b, month, reloadList }) {
  const res = useApi(`/budgets/${b.id}/month`, { month }, ['import', 'share', 'refresh']);
  const v = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} lines=${6} />`;
  const spend = v.rows.filter((/** @type {any} */ r) => r.kind === 'expense' && !r.target);
  const reserveRows = v.rows.filter((/** @type {any} */ r) => r.target);
  const accts = useList('/accounts');
  const names = Object.fromEntries(
    (/** @type {any[]} */ (accts.data) || []).map((a) => [a.id, a.name]),
  );
  const income = v.rows.filter((/** @type {any} */ r) => r.kind === 'income');
  const saving = v.rows.filter((/** @type {any} */ r) => r.kind === 'savings');
  const left = dec(v.plannedSpending).sub(dec(v.spent));
  const sort = async (/** @type {string} */ txnId) => {
    const [txn, accounts] = await Promise.all([
      api.get(`/transactions/${txnId}`),
      api.get('/accounts'),
    ]);
    const done = await openDialog(TransactionDialog, { txn, accounts: accounts.items });
    if (done) res.reload();
  };
  const edit = () => openDialog(PlanDialog, { b, month }).then((x) => x && res.reload());
  const estimate = () =>
    openDialog(EstimateDialog, { b, month, months: 6 }).then((x) => x && res.reload());
  const canMove = b.moves && v.canWrite;
  const moveTo = (/** @type {string} */ to = '') =>
    openDialog(MoveDialog, { b, month, rows: v.rows, to, cards: v.cards }).then((x) =>
      x && res.reload()
    );
  const envelope = b.method === 'envelope';
  const setAside = v.cards.reduce(
    (/** @type {any} */ s, /** @type {any} */ x) => s.add(dec(x.setAside)),
    dec('0'),
  );
  const notBacked = v.cards.reduce(
    (/** @type {any} */ s, /** @type {any} */ x) => s.add(dec(x.notBacked)),
    dec('0'),
  );
  const unmove = async (/** @type {any} */ m) => {
    await api.del(`/budgets/${b.id}/moves/${m.id}`, m.version);
    toast('Move deleted');
    res.reload();
  };
  const settings = () =>
    openDialog(BudgetSettingsDialog, { b }).then((x) => {
      if (x) {
        reloadList();
        res.reload();
      }
    });
  return html`
    ${envelope
      ? html`
        <div class="grid g3">
          <div class="card kpi" data-help="to-budget">
            <div class="label">To Budget</div>
            <div class=${'value amt' + (dec(v.toBudget).isNegative() ? ' down' : '')}>${money(
              v.toBudget,
              { cents: false },
            )}</div>
            <div class="delta dim">${dec(v.toBudget).isNegative()
              ? 'more is assigned than there is'
              : 'left to hand out'}${canMove
              ? html`
                · <button type="button" class="linklike" onClick=${() => moveTo()}>Assign</button>
              `
              : null}</div>
          </div>
          <div class="card kpi">
            <div class="label">Assigned in ${monthLabel(month).split(' ')[0]}</div>
            <div class="value amt">${money(dec(v.assigned).add(dec(v.assignedByMoves)), {
              cents: false,
            })}</div>
            <div class="delta dim">${money(v.assigned, { cents: false })} by the plan, ${money(
              v.assignedByMoves,
              { cents: false },
            )} by moves</div>
          </div>
          <div class="card kpi">
            <div class="label">Set aside for cards</div>
            <div class="value amt">${money(setAside, { cents: false })}</div>
            <div class=${'delta' + (notBacked.gt(0) ? ' down' : ' dim')}>${notBacked.gt(0)
              ? `${money(notBacked)} owed, not backed`
              : 'every card backed'}</div>
          </div>
        </div>
      `
      : html`
        <div class="grid g3">
          <div class="card kpi">
            <div class="label">Income</div>
            <div class="value amt">${money(v.income, {
              cents: false,
            })}</div>
            <div class="delta dim">expected ${money(v.expectedIncome, { cents: false })}</div>
          </div>
          <div class="card kpi">
            <div class="label">Spent</div>
            <div class="value amt">${money(v.spent, {
              cents: false,
            })}</div>
            <div class="delta dim">of ${money(v.plannedSpending, {
              cents: false,
            })} planned · ${money(
              left.abs(),
              { cents: false },
            )} ${left.isNegative() ? 'over' : 'left'}${v.daysLeft
              ? `, ${v.daysLeft} day${v.daysLeft === 1 ? '' : 's'} to go`
              : ''}</div>
          </div>
          <div class="card kpi">
            <div class="label">Saved</div>
            <div class="value amt">${money(v.saved, { cents: false })}</div>
            <div class="delta dim">put away: investing, savings, a loan's principal</div>
          </div>
        </div>
      `}
    <div class="card mt"><h3>${envelope ? 'Envelopes' : 'Categories'}<span class="spacer"></span>
      <span class="small dim" style=${{ fontWeight: 400 }}>${b.level === 'owner'
        ? b.sharedWith ? `shared with ${b.sharedWith}` : 'yours'
        : `${b.ownerName}'s · ${b.level}`}</span>
      ${b.level === 'owner'
        ? html`<button type="button" class="btn sm" onClick=${() =>
          openDialog(ShareDialog, { kind: 'budget', id: b.id, name: b.name }).then(
            reloadList,
          )}><${Icon} name="share" /> Share</button>`
        : null}
      ${v.canWrite
        ? html`
          <button type="button" class="btn sm" onClick=${settings}>Settings</button>
          <button type="button" class="btn sm" onClick=${estimate}>Estimate from history…</button>
          <button type="button" class="btn sm" onClick=${edit}>Edit plan</button>
        `
        : null}</h3>
      ${spend.length
        ? spend.map((/** @type {any} */ r) =>
          html`<${BudgetRow} r=${r} cover=${canMove ? () => moveTo(r.categoryId) : null} />`
        )
        : html`<p class="small dim">Nothing planned for this month yet.${
          v.canWrite
            ? html`
              <button type="button" class="linklike" onClick=${edit}>Plan it</button>
            `
            : ''
        }</p>`}
      ${v.cards.length
        ? html`<h4 class="small dim mt">Cards</h4>${
          v.cards.map((/** @type {any} */ x) =>
            html`
              <div class="budget-row">
                <div>${x.name} <span class="pill">payment</span></div>
                <div class="bar"><i style=${{
                  width: `${
                    num(x.owed) > 0 ? Math.min(1, num(x.setAside) / num(x.owed)) * 100 : 100
                  }%`,
                }}></i></div>
                <div
                  class="num small amt">${money(x.setAside)} <span class="dim">set aside of ${money(
                    x.owed,
                  )} owed</span>${dec(x.notBacked).gt(0)
                    ? html`<div class="down">${money(x.notBacked)} owed, not backed</div>${
                      canMove
                        ? html`<div><button type="button" class="linklike" data-help="cover-from"
                      onClick=${() => moveTo('card:' + x.accountId)}>Cover from…</button></div>`
                        : null
                    }`
                    : null}</div>
              </div>
            `
          )
        }`
        : null}
      ${reserveRows.length
        ? html`<h4 class="small dim mt">Reserves</h4>${
          reserveRows.map((/** @type {any} */ r) =>
            html`<${ReserveRow} r=${r} held=${names[r.heldInId]} />`
          )
        }`
        : null}
      ${v.unplanned.length
        ? html`<h4 class="small dim mt">Not in the plan</h4>${
          v.unplanned.map((/** @type {any} */ u) =>
            html`
              <div class="budget-row">
                <div>${u.label}</div>
                <div></div>
                <div class="num small amt">${money(u.spent)}</div>
              </div>
            `
          )
        }`
        : null}
      ${saving.length
        ? html`<h4 class="small dim mt">Savings</h4>${
          saving.map((/** @type {any} */ r) => html`<${BudgetRow} r=${r} />`)
        }`
        : null}
      ${income.length
        ? html`<h4 class="small dim mt">Income</h4>${
          income.map((/** @type {any} */ r) =>
            html`
              <div class="budget-row">
                <div>${r.label}</div>
                <div class="bar"><i style=${{
                  width: `${Math.min(1, num(r.actual) / Math.max(1, num(r.planned))) * 100}%`,
                }}></i></div>
                <div class="num small amt">${money(r.actual)} <span class="dim">of ${money(
                  r.planned,
                  { cents: false },
                )}</span></div>
              </div>
            `
          )
        }`
        : null}
    </div>
    ${canMove || v.moves.length
      ? html`
        <div class="card mt"><h3>Moves in ${monthLabel(month).split(' ')[0]}<span
          class="spacer"></span>${canMove
            ? html`<button type="button" class="btn sm" onClick=${() => moveTo()}><${Icon}
            name="plus" /> Move</button>`
            : null}</h3>
          ${v.moves.length
            ? v.moves.map((/** @type {any} */ m) =>
              html`
                <div class="list-item">
                  <div class="grow">${money(m.amount)} from ${m.fromLabel} to ${m.toLabel}<div
                    class="small dim">${date(m.createdAt.slice(0, 10))}${m.byName
                      ? ` · ${m.byName}`
                      : ''}${m.note ? ` · “${m.note}”` : ''}</div></div>
                  ${v.canWrite
                    ? html`
                      <button type="button" class="icon-btn" aria-label="Delete the move"
                        onClick=${() => unmove(m).catch((e) => toast(e.message))}><${Icon}
                                            name="x" /></button>
                    `
                    : null}
                </div>
              `
            )
            : html`<p class="small dim">None this month. A move covers one category from another
              for the month: an overspent row offers <b>Cover from…</b>.</p>`}
        </div>
      `
      : null}
    ${v.moved.length
      ? html`
        <div class="card mt"><h3>Left or entered the budget<span class="spacer"></span>
          <span class="small dim" style=${{ fontWeight: 400 }}>transfers with no category count
            nowhere until sorted</span></h3>
          ${v.moved.map((/** @type {any} */ m) =>
            html`
              <div class="list-item">
                <div class="grow">${date(m.date)} · ${dec(m.amount).isNegative()
                  ? `${m.accountName} → ${m.otherAccountName}`
                  : `${m.otherAccountName} → ${m.accountName}`}<div class="small dim">${m.payee ||
                  'a transfer'}</div></div>
                <span class="num amt">${money(m.amount)}</span>
                <button type="button" class="btn sm" data-help="sort" onClick=${() =>
                  sort(m.transactionId)}>Sort</button>
              </div>
            `
          )}
        </div>
      `
      : null}
    ${v.uncategorised
      ? html`<p class="small"><a href="/ui/transactions?category=none">${v.uncategorised} uncategorised
        transaction${v.uncategorised === 1 ? '' : 's'} to sort →</a></p>`
      : null}
  `;
}

/** @param {{ r: any, cover?: (() => void) | null }} p */
function BudgetRow({ r, cover }) {
  const p = num(r.planned) > 0 ? num(r.actual) / num(r.planned) : 1;
  return html`
    <div class="budget-row">
      <div>${r.label}${r.cadence === 'year'
        ? html`
          <span class="pill">year</span>
        `
        : null}</div>
      <div class="bar" role="meter" aria-valuemin="0" aria-valuemax=${r.planned}
        aria-valuenow=${r
          .actual}
        aria-label=${r.label}><i class=${r.state === 'over'
          ? 'over'
          : r.state === 'near'
          ? 'warn'
          : ''} style=${{ width: `${Math.min(p, 1) * 100}%` }}></i></div>
      <div
        class="num small amt">${money(r.actual)} <span class="dim">of ${money(r.planned, {
          cents: false,
        })}</span>${r.state === 'over'
          ? html`
            <span class="pill bad">over</span>
          `
          : null}${r.state === 'over' && cover
          ? html`<div><button type="button" class="linklike" data-help="cover-from"
            onClick=${cover}>Cover from…</button></div>`
          : null}${num(r.moved)
          ? html`<div class="dim">${dec(r.moved).gt(0) ? '+' : '−'}${
            money(dec(r.moved).abs(), { cents: false })
          } moved ${dec(r.moved).gt(0) ? 'in' : 'out'}</div>`
          : null}${num(
            r.carried,
          )
          ? html`<div class="dim">${dec(r.carried).gt(0) ? '+' : '−'}${
            money(
              dec(r.carried).abs(),
              { cents: false },
            )
          } rolled over</div>`
          : null}${r.fromPlan
          ? html`<div class="dim">planned by your <a href=${
            r.fromPlan === 'gifts' ? '/ui/gifts/people' : '/ui/giving'
          }>${r.fromPlan === 'gifts' ? 'gift plans' : 'giving plan'}</a></div>`
          : null}${r.projectionName
          ? html`<div class="dim">${r.projectionName} assumes ${
            money(r.projectionMonthly, {
              cents: false,
            })
          }</div>`
          : null}</div>
    </div>
  `;
}

/**
 * The month's review (S7.14): last month's loose ends, each with its action; Mark reviewed, and
 * a reviewed month flagged when its figures later change. Months are never locked.
 * @param {{ b: any }} p
 */
function Review({ b }) {
  const [y, m] = today().split('-').map(Number);
  const [month, setMonth] = useState(monthKey(new Date(y, m - 2, 1)));
  const res = useApi(`/budgets/${b.id}/review`, { month }, ['import', 'refresh']);
  const v = /** @type {any} */ (res.data);
  const mark = useSubmit(async () => {
    await api.post(`/budgets/${b.id}/review`, { month: month + '-01' });
    toast(`${monthLabel(month)} marked reviewed`);
    res.reload();
  });
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} lines=${5} />`;
  const write = b.level === 'owner' || b.level === 'write';
  const months = Array.from({ length: 12 }, (_, i) => monthKey(new Date(y, m - 2 - i, 1)));
  return html`
    <div class="toolbar">
      <select class="in" style=${{ maxWidth: '180px' }} aria-label="Month reviewed"
        id="f-month-reviewed" value=${month} onChange=${(/** @type {any} */ e) =>
          setMonth(e.currentTarget.value)}>
        ${months.map((x) => html`<option value=${x}>${monthLabel(x)}</option>`)}
      </select>
      <span class="spacer"></span>
      ${write
        ? html`
          <button type="button" class="btn primary" disabled=${mark.busy}
            onClick=${() => mark.run().catch(() => {})}><${Icon} name="check" /> ${v.reviewed
              ? 'Review again'
              : 'Mark reviewed'}</button>
        `
        : null}
    </div>
    ${v.reviewed
      ? html`
        <div class=${'notice' + (v.reviewed.changes.length ? ' warn' : '')} style=${{
          marginBottom: '12px',
        }}>
          <${Icon} name=${v.reviewed.changes.length ? 'alert' : 'check'} />
          <div>Reviewed ${date(
            v.reviewed.at.slice(0, 10),
          )}${v.reviewed.byName ? ` by ${v.reviewed.byName}` : ''}${v.reviewed.changes.length
            ? html`: <b>changed since reviewed</b>. ${v.reviewed.changes.join('; ')}.`
            : '.'}</div>
        </div>
      `
      : null}
    <div class="card"><h3>${monthLabel(month)}</h3>
      ${v.overspent.map((/** @type {any} */ o) =>
        html`
          <div
            class="list-item"><${Icon} name="alert" /><div class="grow">${o.label} was ${money(
              o.over,
            )} over</div><a href=${`/ui/budgets/${b.id}/month`}>See the month</a></div>
        `
      )}
      ${v.toMove.map((/** @type {any} */ x) =>
        html`
          <div
            class="list-item"><${Icon} name="sync" /><div class="grow">${money(
              dec(x.toMove).abs(),
            )} to move ${dec(x.toMove).gt(0) ? 'to' : 'back from'} ${x.accountName}</div><a
                    href=${`/ui/budgets/${b.id}/where`}>Where the money is</a></div>
        `
      )}
      ${v.uncategorised
        ? html`
          <div
            class="list-item"><${Icon} name="tx" /><div class="grow">${v
              .uncategorised} uncategorised transaction${v.uncategorised === 1 ? '' : 's'}</div><a
                    href="/ui/transactions?category=none">Sort</a></div>
        `
        : null}
      ${v.moved
        ? html`
          <div
            class="list-item"><${Icon} name="link" /><div class="grow">${v.moved} transfer${v
                .moved === 1
              ? ''
              : 's'} left or entered the budget without a category</div><a
                    href=${`/ui/budgets/${b.id}/month`}>Sort</a></div>
        `
        : null}
      ${v.toBudget != null && !dec(v.toBudget).isZero()
        ? html`
          <div
            class="list-item"><${Icon} name="info" /><div class="grow">${money(
              v.toBudget,
            )} left in To Budget</div><a href=${`/ui/budgets/${b.id}/month`}>Assign</a></div>
        `
        : null}
      ${!v.overspent.length && !v.toMove.length && !v.uncategorised && !v.moved &&
          (v.toBudget == null || dec(v.toBudget).isZero())
        ? html`<p class="small dim">Nothing left to do for ${monthLabel(month)}.</p>`
        : null}
    </div>
    ${v.history.length
      ? html`
        <div class="card mt"><h3>Months reviewed</h3>
          ${v.history.map((/** @type {any} */ h) =>
            html`
              <div class="list-item">
                <div
                  class="grow">${monthLabel(h.month.slice(0, 7))}${h
                      .changes.length
                    ? html`
                      <span class="pill warn">changed since reviewed</span>
                    `
                    : null}<div class="small dim">reviewed ${date(h.at.slice(0, 10))}${h.byName
                    ? ` by ${h.byName}`
                    : ''}${h.changes.length ? ` · ${h.changes.join('; ')}` : ''}</div></div>
              </div>
            `
          )}
        </div>
      `
      : null}
  `;
}

/**
 * The budgets the user can see: the one they follow, and the scenarios beside it (S7.12).
 * @param {{ budgets: any[], reload: () => void }} p
 */
function BudgetList({ budgets, reload }) {
  const active = budgets.find((x) => x.active);
  const item = (/** @type {any} */ x) =>
    html`
      <div class="list-item">
        <div class="grow"><b>${x.name}</b> <span class="pill">${x.method === 'envelope'
          ? 'Envelope'
          : 'Tracking'}</span>${x.active
          ? html`
            <span class="pill ok">active</span>
          `
          : null}
          <div class="small dim">${x.accountIds.length} account${x.accountIds.length === 1
            ? ''
            : 's'}${x.reserves ? ' · reserves' : ''}${x.moves ? ' · moves' : ''} · ${x.level ===
              'owner'
            ? (x.sharedWith ? `shared with ${x.sharedWith}` : 'yours')
            : `${x.ownerName}'s`}</div></div>
        <a href=${`/ui/budgets/${x.id}/month`}>Open</a>
        ${x.active
          ? null
          : html`<button type="button" class="btn sm" onClick=${() =>
            openDialog(MakeActiveDialog, { b: x, from: active }).then((y) =>
              y && reload()
            )}>Make active</button>`}
        <button type="button" class="btn sm" onClick=${() =>
          openDialog(CopyDialog, { b: x }).then((y) => {
            if (y) location.assign(`/ui/budgets/${y.id}/month`);
          })}>Copy as scenario…</button>
      </div>
    `;
  return html`
    <div class="grid g2">
      <div class="card"><h3>Active<span class="spacer"></span><span class="small dim"
        style=${{ fontWeight: 400 }}>the budget you follow</span></h3>
        ${active ? item(active) : html`<p class="small dim">None: make one active.</p>`}</div>
      <div class="card"><h3>Scenarios<span class="spacer"></span><span class="small dim"
        style=${{ fontWeight: 400 }}>to try another method or plan</span></h3>
        ${budgets.filter((x) => !x.active).map(item)}
        ${budgets.some((x) => !x.active)
          ? null
          : html`<p class="small dim">None yet: <b>Copy as scenario…</b> starts one.</p>`}</div>
    </div>
  `;
}

/**
 * Make a budget the one the user follows (S7.12.1): nothing is rewritten.
 * @param {{ close: (v?: any) => void, b: any, from?: any }} p
 */
function MakeActiveDialog({ close, b, from }) {
  useDialogGuide('dialog-make-active');
  const save = useSubmit(async () => {
    await api.post(`/budgets/${b.id}/active`, {});
    toast(`${b.name} is the budget you follow`);
    close(true);
  });
  return html`
    <${Dialog} title="Make this budget active?" close=${close}
      onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Make active</button>`}>
      <p style=${{ marginTop: 0 }}><b>${b.name}</b> becomes the budget you follow${from
        ? html`, in place of <b>${from.name}</b>, which stays as a scenario`
        : ''}.</p>
      <p class="small dim">Nothing is rewritten: each keeps its months, moves and leave-outs. From
        now on the Dashboard, budget alerts and what to move follow it.</p>
      <${FormError} error=${save.error} />
      </${Dialog}>
  `;
}

/**
 * Copy as scenario (S7.12.4): the same accounts and plan, in the method chosen.
 * @param {{ close: (v?: any) => void, b: any }} p
 */
function CopyDialog({ close, b }) {
  useDialogGuide('dialog-copy');
  const [name, setName] = useState(
    `${b.name}, ${b.method === 'envelope' ? 'tracking' : 'envelope'}`,
  );
  const [method, setMethod] = useState(b.method === 'envelope' ? 'tracking' : 'envelope');
  const [withMoves, setWithMoves] = useState(true);
  const save = useSubmit(async () => {
    const out = await api.post(`/budgets/${b.id}/copy`, { name, method, withMoves }, {
      idempotent: true,
    });
    toast('Copied as a scenario');
    close(out);
  });
  return html`
    <${Dialog} title="Copy as scenario" close=${close} onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Copy</button>`}>
      <${Field} label="Name" error=${errAt(save.error, 'name')}>
        <${Input} value=${name} onInput=${setName} required />
        </${Field}>
        <${Field} label="Method" error=${errAt(save.error, 'method')}
          hint="Each plan line becomes the same amount, planned or assigned each month.">
          <${Select} value=${method} onChange=${setMethod} options=${METHODS} />
          </${Field}>
          <${SwitchRow} label="Bring this month's moves" on=${withMoves} onChange=${setWithMoves} />
          <p class="small dim">The same accounts and plan, from this month. The budget you follow
        doesn't change.</p>
          <${FormError} error=${save.error} shown=${['name', 'method']} />
          </${Dialog}>
  `;
}

/**
 * The budget beside another, per category, for a month or the year to it (S7.12.3).
 * @param {{ b: any, budgets: any[], month: string }} p
 */
function Compare({ b, budgets, month }) {
  const others = budgets.filter((x) => x.id !== b.id);
  const [other, setOther] = useState(
    (others.find((x) => x.active) || others[0])?.id || '',
  );
  const [span, setSpan] = useState('month');
  const res = useApi(other ? `/budgets/${b.id}/compare` : '', { other, month, span });
  const v = /** @type {any} */ (res.data);
  if (!others.length) {
    return html`<${Empty}>Only one budget so far. <b>Copy as scenario…</b> on Budgets makes another
      to compare.</${Empty}>`;
  }
  const otherName = others.find((x) => x.id === other)?.name || '';
  const left = (/** @type {any} */ a, /** @type {any} */ s) =>
    a == null ? '—' : html`<${Amt} v=${String(dec(a).sub(dec(s)))} signed />`;
  return html`
    <div class="toolbar">
      <span class="small dim">${b.name} beside</span>
      <select class="in" style=${{
        maxWidth: '220px',
      }} aria-label="Compared with" id="f-compared-with"
        value=${other} onChange=${(/** @type {any} */ e) => setOther(e.currentTarget.value)}>
        ${others.map((x) => html`<option value=${x.id}>${x.name}</option>`)}
      </select>
      <select class="in" style=${{ maxWidth: '160px' }} aria-label="Range" id="f-range"
        value=${span} onChange=${(/** @type {any} */ e) => setSpan(e.currentTarget.value)}>
        <option value="month">${monthLabel(month)}</option>
        <option value="year">The year to ${monthLabel(month).split(' ')[0]}</option>
      </select>
    </div>
    ${res.error
      ? html`<${Failed} error=${res.error} />`
      : !v
      ? html`<${Loading} lines=${6} />`
      : html`
        <div class="card" style=${{ padding: '4px 8px' }}>
          <table class="t">
            <thead>
              <tr>
                <th></th>
                <th class="num">${b.name}: available</th>
                <th class="num">spent</th>
                <th class="num">left</th>
                <th class="num">${otherName}: available</th>
                <th class="num">spent</th>
                <th class="num">left</th>
              </tr>
            </thead>
            <tbody>${v.rows.map((/** @type {any} */ r) =>
              html`
                <tr>
                  <td>${r.label}</td>
                  <td class="num">${r.available == null
                    ? '—'
                    : html`<${Amt} v=${r.available} />`}</td>
                  <td class="num">${r.spent == null ? '—' : html`<${Amt} v=${r.spent} />`}</td>
                  <td class="num">${left(r.available, r.spent)}</td>
                  <td class="num">${r.otherAvailable == null
                    ? '—'
                    : html`<${Amt} v=${r.otherAvailable} />`}</td>
                  <td class="num">${r.otherSpent == null
                    ? '—'
                    : html`<${Amt} v=${r.otherSpent} />`}</td>
                  <td class="num">${left(r.otherAvailable, r.otherSpent)}</td>
                </tr>
              `
            )}</tbody>
          </table>
        </div>
      `}
  `;
}

/**
 * A move (S7.11): an amount from one category, a reserve among them, to another for the month;
 * in an envelope budget, from or to To Budget.
 * @param {{ close: (v?: any) => void, b: any, month: string, rows: any[], to: string,
 *   cards?: any[] }} p
 */
function MoveDialog({ close, b, month, rows, to, cards = [] }) {
  useDialogGuide('dialog-move');
  const planned = rows.filter((r) => !r.fromPlan && r.kind !== 'income');
  const left = (/** @type {any} */ r) => dec(r.target ? r.balance : r.remaining);
  const envelope = b.method === 'envelope';
  const sources = planned.filter((r) => left(r).gt(0) && r.categoryId !== to).sort((x, y) =>
    left(y).sub(left(x)).isNegative() ? -1 : 1
  );
  const [from, setFrom] = useState(sources[0]?.categoryId || (envelope ? '' : ''));
  const [dest, setDest] = useState(to || planned.find((r) => r.state === 'over')?.categoryId || '');
  const over = planned.find((r) => r.categoryId === dest);
  const card = cards.find((x) => 'card:' + x.accountId === dest);
  const [amount, setAmount] = useState(
    card
      ? String(card.notBacked)
      : over && over.state === 'over'
      ? String(dec(over.remaining).abs())
      : '',
  );
  const [note, setNote] = useState('');
  const save = useSubmit(async () => {
    await api.post(`/budgets/${b.id}/moves`, {
      month: month + '-01',
      fromCategoryId: from || null,
      toCategoryId: dest && !dest.startsWith('card:') ? dest : null,
      cardId: dest.startsWith('card:') ? dest.slice(5) : null,
      amount: amount.replace(/[$,\s]/g, ''),
      note: note || null,
    });
    toast('Moved');
    close(true);
  });
  const label = (/** @type {any} */ r) =>
    `${r.label}${r.target ? ' (reserve)' : ''}: ${money(left(r).abs())} ${
      left(r).isNegative() ? 'over' : 'left'
    }`;
  return html`
    <${Dialog} title=${`Move money: ${monthLabel(month)}`} close=${close}
      onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Move</button>`}>
      <div class="row">
        <${Field} label="From" error=${errAt(save.error, 'fromCategoryId')}>
          <${Select} value=${from} onChange=${setFrom} options=${[
            ...(envelope ? [['', 'To Budget']] : []),
            ...sources.map((r) => [r.categoryId, label(r)]),
          ]} />
          </${Field}>
          <${Field} label="To" error=${errAt(save.error, 'toCategoryId')}>
            <${Select} value=${dest} onChange=${setDest} options=${[
              ...(envelope ? [['', 'To Budget']] : [['', 'Choose a category']]),
              ...planned.filter((r) => r.categoryId !== from).map((r) => [r.categoryId, label(r)]),
              ...cards.map((x) => [
                'card:' + x.accountId,
                `${x.name}'s payment: ${money(x.notBacked)} not backed`,
              ]),
            ]} />
            </${Field}>
            </div>
            <${Field} label="Amount to move" error=${errAt(save.error, 'amount')}>
              <${Input} value=${amount} onInput=${setAmount} inputmode="decimal" required />
              </${Field}>
              <${Field} label="Note" error=${errAt(save.error, 'note')}>
                <${Input} value=${note} onInput=${setNote} placeholder="optional" />
                </${Field}>
                <p class="small dim">For ${monthLabel(
                  month,
                )} only. It shows on both rows and in Activity;
        delete it to undo.</p>
                <${FormError} error=${save.error} shown=${[
                  'fromCategoryId',
                  'toCategoryId',
                  'amount',
                  'note',
                ]} />
                </${Dialog}>
  `;
}

/**
 * A reserve's month (S7.10): its balance against its target, what was put in, spent and moved.
 * @param {{ r: any, held?: string }} p
 */
function ReserveRow({ r, held }) {
  const p = num(r.target) > 0 ? Math.max(0, num(r.balance)) / num(r.target) : 0;
  return html`
    <div class="budget-row">
      <div>${r.label} <span class="pill">reserve</span></div>
      <div class="bar" role="meter" aria-valuemin="0" aria-valuemax=${r.target}
        aria-valuenow=${r.balance}
        aria-label=${r.label}><i class=${r.state === 'over' ? 'over' : ''} style=${{
          width: `${Math.min(p, 1) * 100}%`,
        }}></i></div>
      <div class="num small amt">${money(r.balance, { cents: false })} <span class="dim">of ${money(
        r.target,
        { cents: false },
      )}</span>${r.state === 'funded'
        ? html`
          <span class="pill ok">Funded</span>
        `
        : html`
          <span class="dim" style=${{ marginLeft: '4px' }}>${Math.round(p * 100)}%</span>
        `}
        <div class="dim">${dec(r.putIn).gt(0)
          ? `+${money(r.putIn, { cents: false })} put in`
          : 'nothing put in'}${dec(r.actual).gt(0)
          ? ` · −${money(r.actual, { cents: false })}`
          : ''}${num(
            r.moved,
          )
          ? ` · ${dec(r.moved).gt(0) ? '+' : '−'}${
            money(dec(r.moved).abs(), { cents: false })
          } moved`
          : ''}</div>
        ${held ? html`<div class="dim">in ${held}</div>` : null}</div>
    </div>
  `;
}

/**
 * Where the money is (S7.10.4): each account reserves are held in, what is to move there or
 * back, the money landed there waiting to be given, and each card's payments.
 * @param {{ b: any, month: string }} p
 */
function WhereMoneyIs({ b, month }) {
  const res = useApi(`/budgets/${b.id}/where`, { month }, ['import', 'refresh']);
  const w = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!w) return html`<${Loading} lines=${6} />`;
  if (!w.heldIn.length && !w.cards.length) {
    return html`<${Empty}>No reserve is held in an account, and no card is among the budget's
      accounts. Give a reserve an account it's held in with <b>Edit plan</b>.</${Empty}>`;
  }
  const keepOwn = async (/** @type {any} */ x) => {
    try {
      await api.post(`/budgets/${b.id}/landed`, {
        transactionId: x.transactionId,
        to: 'own',
        amount: String(x.amount),
      }, { params: { month } });
      toast("Kept as the account's own");
      res.reload();
    } catch (e) {
      toast(/** @type {any} */ (e).message);
    }
  };
  const assign = (/** @type {any} */ h, /** @type {any} */ x) =>
    openDialog(AssignDialog, { b, h, landed: x, month }).then((y) => y && res.reload());
  return html`
    <div class="grid g2">${w.heldIn.map((/** @type {any} */ h) =>
      html`
        <div class="card"><h3>${h.accountName}<span class="spacer"></span><span class="small dim"
          style=${{ fontWeight: 400 }}>reserves are held here</span></h3>
          ${h.reserves.map((/** @type {any} */ r) =>
            html`<div class="list-item"><span class="grow">${r.label}</span><span
              class="amt">${money(r.balance)}</span></div>`
          )}
          <div class="list-item"><b class="grow">The reserves</b><b class="amt">${money(
            h.total,
          )}</b></div>
          <div class="list-item"><span class="grow dim">Moved in from the budget's accounts</span><span
            class="amt">${money(h.movedIn)}</span></div>
          ${dec(h.given).gt(0)
            ? html`<div class="list-item"><span class="grow dim">Landed money given to them</span><span
              class="amt">${money(h.given)}</span></div>`
            : null}
          ${h.transfers.map((/** @type {any} */ x) =>
            html`
              <div
                class="list-item"><span class="grow">${x.kept
                  ? "Kept as the account's own"
                  : 'Moved in'}<div class="small dim">${money(x.amount)} ${x.payee ||
                  'a transfer'}, ${date(x.date)}</div></span>${x.kept ? null : html`
                  <button type="button" class="btn sm" data-help="keep-own"
                    onClick=${() => keepOwn(x)}>Keep as the account's own</button>
                `}</div>
            `
          )}
          ${h.unassigned.map((/** @type {any} */ x) =>
            html`
              <div
                class="list-item"><span class="grow">Unassigned<div class="small dim">${money(
                  x.free,
                )} ${x.payee || 'landed'}, ${date(x.date)}</div></span><button type="button"
                            class="btn sm" data-help="unassigned" onClick=${() =>
                              assign(h, x)}>Assign</button></div>
            `
          )}
          <div class="list-item"><span class="grow dim">The account's balance${dec(h.balance).lt(
              dec(h.total),
            )
            ? html`<div class="small down">short of its reserves by ${
              money(
                dec(h.total).sub(dec(h.balance)),
              )
            }</div>`
            : null}</span><span class="amt">${money(h.balance)}</span></div>
          ${h.limit
            ? html`
              <div
                class="list-item"><span class="grow dim">Withdrawals this month</span>${h
                  .withdrawals} of ${h.limit} allowed</div>
            `
            : null}
          ${!w.sayToMove
            ? html`<p class="small dim">This scenario's own figures; only the active budget says what
              to move.</p>`
            : dec(h.toMove).isZero()
            ? html`
              <div class="notice mt">
                <${Icon} name="check" />
                <div><b>Backed</b>: the reserves'
                            money is here.</div>
              </div>
            `
            : html`
              <div class="notice warn mt">
                <${Icon} name="alert" />
                <div><b>${money(
                  dec(h.toMove).abs(),
                )} to move</b> ${dec(h.toMove).gt(0)
                  ? `from ${h.movedFromName || 'checking'} to ${h.accountName}`
                  : `from ${h.accountName} back to ${
                    h.movedFromName || 'checking'
                  }`}. It reads backed once
                            the transfer is imported and paired, whichever of the budget's accounts it involves.${h
                                .overLimit
                              ? html`
                                <b>This would be withdrawal ${h.withdrawals + 1} from ${h
                                  .accountName} this
                                              month; it allows ${h.limit}.</b>
                              `
                              : null}</div>
              </div>
            `}
        </div>
      `
    )}
    ${w.cards.map((/** @type {any} */ c) =>
      html`
        <div class="card"><h3>${c.accountName}<span class="spacer"></span><span class="small dim"
          style=${{ fontWeight: 400 }}>${c.paidFromName
            ? `paid from ${c.paidFromName}`
            : 'no payments yet'}</span></h3>
          <div class="list-item"><span class="grow dim">Owed</span><span class="amt">${money(
            c.owed,
          )}</span></div>
          <div class="list-item"><span class="grow dim">Paid this month</span><span
            class="amt">${money(c.paid)}</span></div>
          ${dec(c.charges).gt(0)
            ? html`<div class="list-item"><span class="grow dim">Interest and fees</span><span
              class="amt">${money(c.charges)}</span></div>`
            : null}
          <p class="small dim">Spending counts when charged; paying the card moves nothing in a tracking
            budget.</p>
        </div>
      `
    )}</div>
  `;
}

/**
 * Landed money given to the reserves held where it landed, or kept as the account's own
 * (S7.10.5).
 * @param {{ close: (v?: any) => void, b: any, h: any, landed: any, month: string }} p
 */
function AssignDialog({ close, b, h, landed, month }) {
  useDialogGuide('dialog-assign');
  const [to, setTo] = useState('spread');
  const [amount, setAmount] = useState(String(landed.free));
  const save = useSubmit(async () => {
    await api.post(`/budgets/${b.id}/landed`, {
      transactionId: landed.transactionId,
      to,
      amount: amount.replace(/[$,\s]/g, ''),
    }, { params: { month } });
    toast('Assigned');
    close(true);
  });
  return html`
    <${Dialog} title="Assign landed money" close=${close}
      onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Assign</button>`}>
      <p
        style=${{ marginTop: 0 }}>${money(landed.amount)} ${landed.payee || 'landed'} in ${h
          .accountName} on ${date(
            landed.date,
          )}. In the budget it counts as it always does; this says
        whose it is.</p>
      <${Field} label="Give it to" error=${errAt(save.error, 'to')}>
        <${Select} value=${to} onChange=${setTo} options=${[
          ['spread', 'Spread among the reserves held here, by balance'],
          ...h.reserves.map((/** @type {any} */ r) => [r.categoryId, r.label]),
          ['own', "Keep it as the account's own"],
        ]} />
        </${Field}>
        <${Field} label="Amount to assign" error=${errAt(save.error, 'amount')}>
          <${Input} value=${amount} onInput=${setAmount} inputmode="decimal" required />
          </${Field}>
          <${FormError} error=${save.error} shown=${['to', 'amount']} />
          </${Dialog}>
  `;
}

/** @param {{ b: any, month: string }} p */
function CashFlow({ b, month }) {
  const res = useApi(`/budgets/${b.id}/cash-flow`, { month });
  const f = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!f) return html`<${Loading} lines=${6} />`;
  return html`
    <div class="card"><h3>${monthLabel(month)}: where the money went</h3>
      ${f.sources.length || f.uses.length
        ? html`
          <${FlowChart} label=${`Cash flow, ${monthLabel(month)}`} sources=${f.sources}
            uses=${f.uses} />
        `
        : html`<p class="small dim">No categorised income or spending this month.</p>`}
      <p class="small dim">In ${money(f.income)} · out ${money(f.spending)}. Transfers between your
        accounts aren't counted.</p>
    </div>
  `;
}

/** @param {{ b: any, month: string }} p */
function Trends({ b, month }) {
  const cats = useList('/categories');
  const [category, setCategory] = useState('');
  const res = useList(`/budgets/${b.id}/trends`, { month, category: category || undefined });
  const t = /** @type {any[]} */ (res.data);
  const options = /** @type {[string, string][]} */ ([
    ['', 'All spending'],
    ...(/** @type {any[]} */ (cats.data) || []).filter((c) => c.kind === 'expense').map((
      c,
    ) => [c.id, c.path]),
  ]);
  return html`
    <div class="card"><h3>Spending by month<span class="spacer"></span>
      <select class="in" style=${{ maxWidth: '220px' }} aria-label="Category" id="f-category"
        value=${category} onChange=${(/** @type {any} */ e) => setCategory(e.currentTarget.value)}>
        ${options.map(([v, l]) => html`<option value=${v}>${l}</option>`)}
      </select></h3>
      ${res.error
        ? html`<${Failed} error=${res.error} />`
        : !t
        ? html`<${Loading} lines=${6} />`
        : html`
          <${BarChart} label="Planned and actual spending by month"
            periods=${t.map((p) =>
              new Date(p.month + 'T12:00:00').toLocaleDateString('en-US', { month: 'short' })
            )}
            series=${[
              { name: 'Planned', color: '--border-strong', values: t.map((p) => p.planned) },
              { name: 'Actual', color: '--c1', values: t.map((p) => p.actual) },
            ]} />
        `}
    </div>
  `;
}

/** @param {{ b: any }} p */
function Recurring({ b }) {
  const res = useList(`/budgets/${b.id}/recurring`, {}, ['import']);
  const rows = /** @type {any[]} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!rows) return html`<${Loading} lines=${6} />`;
  if (!rows.length) {
    return html`<${Empty}>Nothing recurring found yet. A payee needs three or more payments at a
      steady interval.</${Empty}>`;
  }
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <table class="t">
        <thead>
          <tr>
            <th>Payee</th>
            <th>Every</th>
            <th>Next</th>
            <th class="num">Expected</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows.map((r) =>
          html`
            <tr>
              <td>${r.payee}<div class="small dim">${r.accountName}</div></td>
              <td class="dim">${r.every}</td>
              <td>${date(r.next)}</td>
              <td class="num amt">${money(r.usual)}</td>
              <td>${r.missed
                ? html`<span class="pill bad">missed</span>`
                : r.changed
                ? html`<span class="pill warn">last one ${
                  Math.round(
                    Math.abs(num(r.lastAmount) / num(r.usual) - 1) * 100,
                  )
                }% ${dec(r.lastAmount).abs().gt(dec(r.usual).abs()) ? 'higher' : 'lower'}</span>`
                : null}</td>
            </tr>
          `
        )}</tbody>
      </table>
    </div>
  `;
}

/**
 * What the budget's accounts await being paid back (S2.9), oldest first, with the deposits that
 * may pay each back.
 * @param {{ b: any }} p
 */
function Reimbursements({ b }) {
  const res = useList(`/budgets/${b.id}/reimbursements`, {}, ['import']);
  const rows = /** @type {any[]} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!rows) return html`<${Loading} lines=${4} />`;
  if (!rows.length) {
    return html`<${Empty}>Nothing awaits being paid back. Mark spending <b>Reimbursable</b> in its
      transaction, and it's listed here, not counted, until a deposit pays it back.</${Empty}>`;
  }
  const pair = (/** @type {any} */ r) =>
    openDialog(PairDialog, { item: r }).then((x) => x && res.reload());
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <h3 style=${{ padding: '8px 8px 0' }}>Awaiting reimbursement<span class="spacer"></span>
        <span class="small dim" style=${{ fontWeight: 400 }}>not counted while awaited</span></h3>
      <table class="t">
        <thead>
          <tr>
            <th>Spent</th>
            <th>Payee</th>
            <th>Category</th>
            <th>Owed by</th>
            <th class="num">Awaited</th>
            <th>Age</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${rows.map((r) =>
          html`
            <tr>
              <td>${date(r.date)}</td>
              <td>${r.payee || '—'}${r.splitId
                ? html`
                  <span class="small dim">(one part)</span>
                `
                : null}<div class="small dim">${r.accountName}</div></td>
              <td>${r.category || '—'}</td>
              <td>${r.owedBy || '—'}</td>
              <td class="num amt">${money(r.awaited)}${dec(r.paidBack).gt(0)
                ? html`<div class="small dim">of ${money(r.reimbursable)}</div>`
                : null}</td>
              <td>${r.ageDays} day${r.ageDays === 1 ? '' : 's'}</td>
              <td><button type="button" class="btn sm" data-help="pair" disabled=${!r.offers
                .length} onClick=${() => pair(r)}>Pair a payback</button></td>
            </tr>
          `
        )}</tbody>
      </table>
    </div>
  `;
}

/**
 * Pair a deposit with spending awaiting being paid back.
 * @param {{ close: (v?: any) => void, item: any }} p
 */
function PairDialog({ close, item }) {
  useDialogGuide('dialog-pair');
  const [pick, setPick] = useState(item.offers[0]?.transactionId || '');
  const offer = item.offers.find((/** @type {any} */ o) => o.transactionId === pick);
  const most = offer
    ? (dec(offer.free).lt(dec(item.awaited)) ? offer.free : item.awaited)
    : item.awaited;
  const [amount, setAmount] = useState(String(most));
  const save = useSubmit(async () => {
    await api.post('/reimbursements', {
      spendingId: item.spendingId,
      splitId: item.splitId,
      paybackId: pick,
      amount: String(amount).replace(/[$,\s]/g, ''),
    });
    toast('Paired: that much is paid back');
    close(true);
  });
  return html`
    <${Dialog} title="Pair a payback" close=${close} onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy || !pick}>Pair</button>`}>
      <p style=${{ marginTop: 0 }}>${item.payee || 'Spending'}, ${date(item.date)}: ${money(
        item.awaited,
      )} awaited${item.owedBy ? ` from ${item.owedBy}` : ''}.</p>
      <fieldset class="field" style=${{ border: 0, padding: 0, margin: '0 0 14px' }}>
        <legend class="small" style=${{
          color: 'var(--fg-dim)',
        }}>Deposits that may pay it back</legend>
        ${item.offers.map((/** @type {any} */ o) =>
          html`<label class="list-item" style=${{ cursor: 'pointer' }}><input type="radio"
            name="payback" data-help="deposits" checked=${
            o.transactionId === pick
          } onChange=${() => {
            setPick(o.transactionId);
            setAmount(String(dec(o.free).lt(dec(item.awaited)) ? o.free : item.awaited));
          }} /><span class="grow">${o.payee || 'A deposit'}<div class="small dim">${
            date(
              o.date,
            )
          } · ${o.accountName}</div></span><span class="amt">${money(o.free)}</span></label>`
        )}
      </fieldset>
      <${Field} label="Pays back" error=${errAt(save.error, 'amount')}
        hint="All of it, or part; one deposit can pay back several.">
        <${Input} value=${amount} onInput=${setAmount} inputmode="decimal" required />
        </${Field}>
        <${FormError} error=${save.error} shown=${['amount']} />
        </${Dialog}>
  `;
}

/**
 * The accounts a budget covers, with a note naming those it leaves out that often get transfers
 * from them (S7.3.2).
 * @param {{ ids: Set<string>, setIds: (s: Set<string>) => void, error: any }} p
 */
function AccountsPicker({ ids, setIds, error }) {
  const accounts = useList('/accounts');
  const outside = useList('/budgets/left-out', { accountIds: [...ids].sort() });
  const left = /** @type {any[]} */ (outside.data) || [];
  const list = /** @type {any[]} */ (accounts.data) || [];
  return html`
    <fieldset class="field" style=${{ border: 0, padding: 0, margin: '0 0 14px' }}>
      <legend class="small" style=${{ color: 'var(--fg-dim)' }}>Accounts</legend>
      ${list.filter((a) => !a.investing).map((a) =>
        html`<label class="list-item" style=${{ cursor: 'pointer' }}><input type="checkbox"
          data-help="accounts" checked=${ids.has(a.id)} onChange=${() => {
          const next = new Set(ids);
          next.has(a.id) ? next.delete(a.id) : next.add(a.id);
          setIds(next);
        }} /><span class="grow">${a.name} <span class="small dim">${
          a.institution || ''
        }</span></span></label>`
      )}
      ${errAt(error, 'accountIds')
        ? html`<div class="err">${errAt(error, 'accountIds')}</div>`
        : null}
    </fieldset>
    ${left.map((x) =>
      html`
        <div class="notice" style=${{ marginBottom: '12px' }}>
          <${Icon} name="info" />
          <div><b>${x.name}</b> gets transfers from these accounts (${x.transfers} this year):
            <button type="button" class="linklike" onClick=${() =>
              setIds(new Set([...ids, x.accountId]))}>include it?</button> Left out, a
            transfer to it counts by its category, or waits to be sorted.</div>
        </div>
      `
    )}
  `;
}

const METHODS = /** @type {[string, string][]} */ ([
  ['tracking', 'Tracking: a plan against what is spent'],
  ['envelope', 'Envelope: hand out the money you have'],
]);

/**
 * A new budget: its name, method, options and accounts, and whether to plan it from history.
 * @param {{ close: (v?: any) => void }} p
 */
function BudgetDialog({ close }) {
  useDialogGuide('dialog-budget');
  const [name, setName] = useState('');
  const [method, setMethod] = useState('tracking');
  const [reserves, setReserves] = useState(true);
  const [moves, setMoves] = useState(true);
  const [estimate, setEstimate] = useState('6');
  const [ids, setIds] = useState(/** @type {Set<string>} */ (new Set()));
  const save = useSubmit(async () => {
    const out = await api.post('/budgets', {
      name,
      accountIds: [...ids],
      method,
      reserves,
      moves: moves || method === 'envelope',
    }, { idempotent: true });
    toast('Budget made');
    close({ ...out, estimate: Number(estimate) || 0 });
  });
  return html`
    <${Dialog} title="New budget" wide close=${close} onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Make it</button>`}>
      <${Field} label="Name" error=${errAt(save.error, 'name')}>
        <${Input} value=${name} onInput=${setName} placeholder="Household" required />
        </${Field}>
        <${Field} label="Method" error=${errAt(save.error, 'method')}
          hint="It keeps its method; copy it as a scenario to try the other.">
          <${Select} value=${method} onChange=${setMethod} options=${METHODS} />
          </${Field}>
          <${SwitchRow} label="Reserves" hint="Save toward a target in a category, month by month."
            on=${reserves} onChange=${setReserves} />
          <${SwitchRow} label="Moves" hint=${method === 'envelope'
            ? 'Always on in an envelope budget.'
            : 'Cover one category from another for a month.'} on=${moves ||
            method === 'envelope'} onChange=${setMoves}
            disabled=${method === 'envelope'} />
          <${AccountsPicker} ids=${ids} setIds=${setIds} error=${save.error} />
          <${Field} label="Estimate from history"
            hint="A plan line per category from its average; you keep, change or drop each.">
            <${Select} value=${estimate} onChange=${setEstimate} options=${[
              ['0', "Don't estimate"],
              ['3', 'The last 3 months'],
              ['6', 'The last 6 months'],
              ['12', 'The last 12 months'],
            ]} />
            </${Field}>
            <${FormError} error=${save.error} shown=${['name', 'accountIds', 'method']} />
            </${Dialog}>
  `;
}

/**
 * A budget's name, options and accounts, and where its money comes from (S7.1.6).
 * @param {{ close: (v?: any) => void, b: any }} p
 */
function BudgetSettingsDialog({ close, b }) {
  useDialogGuide('dialog-budget-settings');
  const accounts = useList('/accounts');
  const list = /** @type {any[]} */ (accounts.data) || [];
  const byId = Object.fromEntries(list.map((a) => [a.id, a]));
  const [name, setName] = useState(b.name);
  const [reserves, setReserves] = useState(b.reserves);
  const [moves, setMoves] = useState(b.moves);
  const [ids, setIds] = useState(/** @type {Set<string>} */ (new Set(b.accountIds)));
  const [roles, setRoles] = useState(
    Object.fromEntries(
      b.roles.map((/** @type {any} */ r) => [r.accountId, {
        paidFromId: r.paidFromLearned ? '' : r.paidFromId || '',
        movedFromId: r.movedFromProposed ? '' : r.movedFromId || '',
      }]),
    ),
  );
  const learned = Object.fromEntries(b.roles.map((/** @type {any} */ r) => [r.accountId, r]));
  const owner = b.level === 'owner';
  const save = useSubmit(async () => {
    await api.patch(`/budgets/${b.id}`, {
      name,
      reserves,
      moves,
      ...(owner ? { accountIds: [...ids] } : {}),
      roles: b.roles.map((/** @type {any} */ r) => ({
        accountId: r.accountId,
        paidFromId: roles[r.accountId]?.paidFromId || null,
        movedFromId: roles[r.accountId]?.movedFromId || null,
      })),
    }, b.version);
    toast('Saved');
    close(true);
  });
  const inBudget = b.accountIds.map((/** @type {string} */ x) => byId[x]).filter(Boolean);
  const choices = (/** @type {any} */ a, /** @type {string} */ k) => {
    const r = learned[a.id];
    const auto = k === 'paidFromId' ? r?.paidFromId : r?.movedFromId;
    return [
      ['', `As its history says${auto && byId[auto] ? `: ${byId[auto].name}` : ''}`],
      ...inBudget.filter((x) => x.id !== a.id && x.type !== 'credit-card').map((x) => [
        x.id,
        x.name,
      ]),
    ];
  };
  const set = (/** @type {string} */ id, /** @type {string} */ k) => (/** @type {string} */ v) =>
    setRoles({ ...roles, [id]: { ...roles[id], [k]: v } });
  return html`
    <${Dialog} title=${`${b.name}: settings`} wide close=${close}
      onSubmit=${() => save.run().catch(() => {})}
      note=${`${
        b.method === 'envelope' ? 'An envelope' : 'A tracking'
      } budget: it keeps its method.`}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Save</button>`}>
      <${Field} label="Name" error=${errAt(save.error, 'name')}>
        <${Input} value=${name} onInput=${setName} required /></${Field}>
      <${SwitchRow} label="Reserves" hint="Save toward a target in a category, month by month."
        on=${reserves} onChange=${setReserves} />
      <${SwitchRow} label="Moves" hint=${b.method === 'envelope'
        ? 'Always on in an envelope budget.'
        : 'Cover one category from another for a month.'} on=${moves} onChange=${setMoves}
        disabled=${b.method === 'envelope'} />
      ${owner ? html`<${AccountsPicker} ids=${ids} setIds=${setIds} error=${save.error} />` : null}
      <fieldset class="field" style=${{ border: 0, padding: 0, margin: '0 0 14px' }}>
        <legend class="small" style=${{ color: 'var(--fg-dim)' }}>Where money comes from</legend>
        ${[
          ...inBudget.filter((a) => a.type === 'credit-card'),
          ...inBudget.filter((a) => a.type !== 'credit-card'),
        ].map((a) =>
          a.type === 'credit-card'
            ? html`<div class="list-item"><span class="grow">${a.name}<div class="small dim">paid
              from</div></span><${Select} value=${roles[a.id]?.paidFromId || ''}
              onChange=${set(a.id, 'paidFromId')} options=${choices(a, 'paidFromId')}
              aria-label=${`${a.name}: paid from`} data-help="paid-from" /></div>`
            : ['savings', 'money-market'].includes(a.type)
            ? html`<div class="list-item"><span class="grow">${a.name}<div class="small dim">money
              for its reserves moves from</div></span><${Select} value=${
              roles[a.id]?.movedFromId ||
              ''
            } onChange=${set(a.id, 'movedFromId')} options=${choices(a, 'movedFromId')}
              aria-label=${`${a.name}: moved from`} data-help="moved-from" /></div>`
            : null
        )}
      </fieldset>
      <${FormError} error=${save.error} shown=${['name', 'accountIds']} />
    </${Dialog}>
  `;
}

/**
 * A plan line as a dialog's draft edits it (S7.1.2, S12.15): stored as it was read, changed
 * from the month the dialog plans from, and taken out by setting it to nothing from then.
 */
class PlanLine extends Record {
  /** @override */
  static prefix = 'BdgLn';
  /** @override */
  static fields = FIELDS.LineIn;
  /** @override */
  static defaults = {
    amount: Dec.parse('0.00'),
    cadence: 'month',
    rollover: false,
    overspend: 'carry',
    projectionId: null,
    target: null,
    heldInId: null,
  };
  /** @override */
  static rules = {
    // A reserve is a monthly line in a budget with reserves; its money is held somewhere.
    target: { when: (/** @type {PlanLine} */ r) => r.reserves && r.get('cadence') === 'month' },
    heldInId: { when: (/** @type {PlanLine} */ r) => r.get('target') != null },
    // A projection follows a savings category only.
    projectionId: {
      when: (/** @type {PlanLine} */ r) => r.kinds[r.get('categoryId')] === 'savings',
    },
  };
  /** @override */
  static removal = (/** @type {PlanLine} */ r) => ({
    amount: Dec.parse('0.00'),
    target: null,
    heldInId: null,
    fromMonth: r.asOf,
  });
  /** The first day of the month the dialog plans from: each change holds from then. */
  asOf = '';
  reserves = false;
  /** Each category's kind, for the rules. @type {{ [id: string]: string }} */
  kinds = {};

  /** @override */
  changes() {
    const out = super.changes();
    if (this.state !== 'new' && Object.keys(out).length) out.fromMonth = this.asOf;
    return out;
  }
}

/**
 * The plan in force in a month, read as stored into a draft (never the month's figures, which
 * carry remainders and moves: CR3-2), with the categories for its rules and labels.
 * @param {any} b @param {string} month
 */
function usePlanDraft(b, month) {
  const [state, setState] = useState(
    /** @type {{ draft: Draft | null, error: any, tick: number }} */ ({
      draft: null,
      error: null,
      tick: 0,
    }),
  );
  const cats = useList('/categories');
  const kinds = Object.fromEntries(
    (/** @type {any[]} */ (cats.data) || []).map((c) => [c.id, c.kind]),
  );
  const paths = Object.fromEntries(
    (/** @type {any[]} */ (cats.data) || []).map((c) => [c.id, c.path]),
  );
  useEffect(() => {
    let live = true;
    api.get(`/budgets/${b.id}/plan`, { month }).then((p) => {
      if (!live) return;
      const draft = new Draft();
      for (const ln of p.lines) draft.load(PlanLine, ln);
      setState({ draft, error: null, tick: state.tick });
    }, (error) => live && setState({ draft: null, error, tick: state.tick }));
    return () => {
      live = false;
    };
  }, [b.id, month, state.tick]);
  const draft = state.draft;
  if (draft) {
    for (const r of /** @type {PlanLine[]} */ (draft.records)) {
      r.asOf = month + '-01';
      r.reserves = !!b.reserves;
      r.kinds = kinds;
    }
  }
  /** Read the plan again, the changes made here dropped (S12.15.5). */
  const reload = () => setState({ draft: null, error: null, tick: state.tick + 1 });
  /** A new line, from the month planned. @param {any} [data] */
  const add = (data = {}) => {
    const r = /** @type {PlanLine} */ (
      draft?.add(PlanLine, { budgetId: b.id, fromMonth: month + '-01', categoryId: '', ...data })
    );
    r.asOf = month + '-01';
    r.reserves = !!b.reserves;
    r.kinds = kinds;
    return r;
  };
  return { draft, error: state.error, reload, add, kinds, paths, cats };
}

/**
 * What a draft's save came to, above the buttons: its questions, listed together; a record
 * changed meanwhile; a refusal that belongs to no field (S12.15.4, S12.15.5).
 * @param {{ outcome: any, draft: Draft | null }} p
 */
function SaveOutcome({ outcome, draft }) {
  if (outcome?.status === 'asks') {
    return html`
      <div class="notice warn" role="alert">
        <${Icon} name="alert" />
        <div>Saving this asks ${outcome.asks.length === 1 ? 'one thing' : 'these'} first:<ol
            class="asks">${outcome.asks.map((/** @type {any} */ a) =>
              html`<li>${a.message}</li>`
            )}</ol></div>
      </div>
    `;
  }
  if (outcome?.status === 'stale') {
    return html`
      <div class="notice warn" role="alert">
        <${Icon} name="alert" />
        <div>The plan changed since you opened it, so nothing was saved. <b>Reload</b> opens it as
          it stands; what you changed here is lost.</div>
      </div>
    `;
  }
  if (draft?.formError) {
    return html`
      <div class="notice warn" role="alert">
        <${Icon} name="alert" />
        <div>${draft
          .formError}</div>
      </div>
    `;
  }
  return null;
}

/**
 * A draft's Save, with the questions its last save asked confirmed by name (S12.15.4).
 * @param {Draft | null} draft @param {(v?: any) => void} close
 */
function useDraftSave(draft, close) {
  const [outcome, setOutcome] = useState(/** @type {any} */ (null));
  const save = useSubmit(async () => {
    if (!draft) return;
    const o = await draft.save({ confirmAsks: outcome?.status === 'asks' });
    setOutcome(o);
    if (o.status === 'saved') {
      toast('Plan saved');
      close(true);
    }
  });
  return { save, outcome, setOutcome };
}

/**
 * A plan estimated from history (S7.1.5): each proposed line kept, changed or dropped, then
 * saved into the plan from the month shown on. Lines it doesn't propose stay as they are.
 * @param {{ close: (v?: any) => void, b: any, month: string, months: number }} p
 */
function EstimateDialog({ close, b, month, months }) {
  useDialogGuide('dialog-estimate');
  const [span, setSpan] = useState(String(months));
  const res = useList(`/budgets/${b.id}/estimate`, { months: span });
  const found = /** @type {any[]} */ (res.data) || [];
  const [drop, setDrop] = useState(/** @type {Set<string>} */ (new Set()));
  const [amounts, setAmounts] = useState(/** @type {{ [id: string]: string }} */ ({}));
  const p = usePlanDraft(b, month);
  const { save, outcome, setOutcome } = useDraftSave(p.draft, close);
  // The proposals chosen, put into the plan's draft: an existing line takes the amount and
  // cadence, and keeps the rest of what it has (its target, where it is held).
  const apply = () => {
    const draft = p.draft;
    if (!draft) return;
    draft.revertAll();
    const byCat = new Map(
      /** @type {PlanLine[]} */ (draft.records).map((r) => [r.get('categoryId'), r]),
    );
    for (const x of found) {
      if (drop.has(x.categoryId)) continue;
      const typed = amounts[x.categoryId];
      const r = byCat.get(x.categoryId) || p.add({ categoryId: x.categoryId });
      if (typed === undefined) r.set('amount', x.amount);
      else if (!r.input('amount', typed)) return false;
      r.set('cadence', x.cadence);
      if (r.state === 'new' && b.reserves && x.target) r.set('target', x.target);
    }
    return true;
  };
  const changed = () => drop.size > 0 || Object.keys(amounts).length > 0;
  return html`
    <${Dialog} title="Plan from history" wide close=${close} changed=${changed}
      onSubmit=${() => {
        if (apply()) save.run().catch(() => {});
      }} note="Nothing is saved until you save."
      footer=${html`<button class="btn primary" disabled=${
        save.busy || !found.length ||
        !p.draft
      }>${outcome?.status === 'asks' ? 'Save anyway' : 'Save the plan'}</button>`}>
      <${Field} label="Months to average" id="months">
        <${Select} value=${span} onChange=${(/** @type {string} */ v) => {
          setSpan(v);
          setOutcome(null);
        }} options=${[
          ['3', 'The last 3 months'],
          ['6', 'The last 6 months'],
          ['12', 'The last 12 months'],
        ]} /></${Field}>
      ${res.error || p.error
        ? html`<${Failed} error=${res.error || p.error} />`
        : !res.data || !p.draft
        ? html`<${Loading} lines=${4} />`
        : !found.length
        ? html`<p class="small dim">Nothing to go by yet: no categorised spending in those months.</p>`
        : html`
          <table class="t plan">
            <thead>
              <tr>
                <th></th>
                <th>Category</th>
                <th class="num">Amount</th>
                <th>Every</th>
                <th>From</th>
              </tr>
            </thead>
            <tbody>${found.map((x) => {
              const r = /** @type {PlanLine | undefined} */ (p.draft?.records.find((y) =>
                y.get('categoryId') === x.categoryId && y.state === 'new'
              ) || p.draft?.records.find((y) =>
                y.get('categoryId') === x.categoryId
              ));
              return html`
                <tr>
                  <td><input type="checkbox" aria-label=${`Keep ${x.label}`} data-help="keep"
                    checked=${!drop.has(x.categoryId)} onChange=${() => {
                      const next = new Set(drop);
                      next.has(x.categoryId) ? next.delete(x.categoryId) : next.add(x.categoryId);
                      setDrop(next);
                      setOutcome(null);
                    }} /></td>
                  <td>${x.label}</td>
                  <td class="num">
                    <${Input} value=${amounts[x.categoryId] ?? money(x.amount).slice(1)}
                      onInput=${(/** @type {string} */ v) => {
                        setAmounts({ ...amounts, [x.categoryId]: v });
                        setOutcome(null);
                      }}
                      inputmode="decimal" aria-label=${`${x.label}: amount`} data-help="amount"
                      bad=${r?.error('amount')} />
                  </td>
                  <td>${x.cadence === 'year' ? 'Year' : 'Month'}</td>
                  <td class="small dim">${x.detail}${x.target
                    ? `; a reserve toward ${money(x.target, { cents: false })}`
                    : ''}</td>
                </tr>
              `;
            })}</tbody>
          </table>
        `}
      <${SaveOutcome} outcome=${outcome} draft=${p.draft} />
      <${FormError} error=${save.error} />
    </${Dialog}>
  `;
}

/**
 * The plan from the month shown on: a line per category, monthly or yearly, rolling over or
 * not. Earlier months keep the plan they had. Edited as a draft of the lines as stored, so a
 * dialog saved unchanged changes nothing (S12.15, CR3-2).
 * @param {{ close: (v?: any) => void, b: any, month: string }} p
 */
function PlanDialog({ close, b, month }) {
  useDialogGuide('dialog-plan');
  const projections = useList('/projections');
  const p = usePlanDraft(b, month);
  const draft = p.draft;
  const { save, outcome, setOutcome } = useDraftSave(draft, close);
  const accounts = useList('/accounts');
  const heldOptions = /** @type {[string, string][]} */ ([
    ['', '—'],
    ...(/** @type {any[]} */ (accounts.data) || []).filter((a) =>
      b.accountIds.includes(a.id) && a.type !== 'credit-card'
    ).map((a) => [a.id, a.name]),
  ]);
  const plans = /** @type {[string, string][]} */ ([
    ['', 'None'],
    ...(/** @type {any[]} */ (projections.data) || []).filter((x) => x.active).map((x) => [
      x.id,
      x.name,
    ]),
  ]);
  const envelope = b.method === 'envelope';
  const taken = new Set(
    (draft?.records || []).filter((r) => !r.removed).map((r) => r.get('categoryId')),
  );
  const options = /** @type {[string, string][]} */ ([
    ['', 'Choose a category'],
    ...(/** @type {any[]} */ (p.cats.data) || []).filter((c) => c.kind !== 'transfer').map((
      c,
    ) => [c.id, c.path]),
  ]);
  const rows = /** @type {PlanLine[]} */ ((draft?.records || []).filter((r) => !r.removed));
  /** @param {PlanLine} r @param {string} k */
  const pick = (r, k) => (/** @type {any} */ v) => {
    r.set(k, v === '' ? null : v);
    setOutcome(null);
  };
  /** @param {PlanLine} r @param {string} k */
  const typed = (r, k) => (/** @type {string} */ v) => {
    r.input(k, v);
    setOutcome(null);
  };
  const submit = () => {
    if (!draft) return;
    // A line added and left without a category is no line.
    for (const r of rows) if (r.state === 'new' && !r.get('categoryId')) draft.remove(r);
    save.run().catch(() => {});
  };
  return html`
    <${Dialog} title=${`Plan from ${monthLabel(month)}`} wide close=${close}
      changed=${() => !!draft?.changed} onSubmit=${submit}
      note="Earlier months keep the plan they had."
      footer=${outcome?.status === 'stale'
        ? html`<button type="button" class="btn primary" onClick=${() => {
          setOutcome(null);
          p.reload();
        }}>Reload</button>`
        : html`<button class="btn primary" disabled=${save.busy || !draft}>${
          outcome?.status === 'asks' ? 'Save anyway' : 'Save'
        }</button>`}>
      ${p.error
        ? html`<${Failed} error=${p.error} />`
        : !draft
        ? html`<${Loading} lines=${4} />`
        : html`
          <table class="t plan">
            <thead>
              <tr>
                <th>Category</th>
                <th class="num">Amount</th>
                <th>Every</th>
                <th>Rollover</th>
                ${envelope ? html`<th>Overspent</th>` : null}
                ${b.reserves
                  ? html`
                    <th class="num">Target</th>
                    <th>Held in</th>
                  `
                  : null}
                <th>Projection</th>
                <th></th>
              </tr>
            </thead>
            <tbody>${rows.map((r) =>
              html`
                <tr key=${r.key}>
                  <td>${r.state === 'new'
                    ? html`
                      <${Select} value=${r.get('categoryId') || ''} onChange=${pick(
                        r,
                        'categoryId',
                      )}
                        options=${options.filter(([id]) =>
                          !id || id === r.get('categoryId') || !taken.has(id)
                        )} aria-label="Category" data-help="category"
                        bad=${r.error('categoryId')} />
                    `
                    : p.paths[r.get('categoryId')] || 'A category'}</td>
                  <td class="num">
                    <${Input} value=${r.shown('amount')} onInput=${typed(r, 'amount')}
                      inputmode="decimal" aria-label="Amount" data-help="amount"
                      bad=${r.error('amount')} />
                  </td>
                  <td>
                    <${Select} value=${r.get('cadence')} onChange=${pick(r, 'cadence')}
                      options=${[['month', 'Month'], ['year', 'Year']]} aria-label="Every"
                      data-help="every" />
                  </td>
                  <td>
                    <${Switch} on=${r.get('rollover')} onChange=${pick(r, 'rollover')}
                      label="Rollover" help="rollover" disabled=${r.get('cadence') === 'year'} />
                  </td>
                  ${envelope
                    ? html`
                      <td>
                        <${Select} value=${r.get('overspend')} onChange=${pick(r, 'overspend')}
                          options=${[
                            ['carry', 'Carried negative'],
                            ['next', "From next month's To Budget"],
                          ]} aria-label="Overspent" data-help="overspent" />
                      </td>
                    `
                    : null}
                  ${b.reserves
                    ? html`
                      <td class="num">${r.applies('target')
                        ? html`
                          <${Input} value=${r.shown('target')} onInput=${typed(r, 'target')}
                            inputmode="decimal" placeholder="none" aria-label="Target"
                            data-help="target" bad=${r.error('target')}
                            style=${{ width: '90px', textAlign: 'right' }} />
                        `
                        : null}</td>
                      <td>${r.applies('heldInId')
                        ? html`
                          <${Select} value=${r.get('heldInId') || ''} onChange=${pick(
                            r,
                            'heldInId',
                          )} options=${heldOptions} aria-label="Held in"
                            data-help="held-in" />
                        `
                        : null}</td>
                    `
                    : null}
                  <td>${r.applies('projectionId')
                    ? html`
                      <${Select} value=${r.get('projectionId') || ''} onChange=${pick(
                        r,
                        'projectionId',
                      )} options=${plans} aria-label="Projection"
                        data-help="projection" />
                    `
                    : null}</td>
                  <td><button type="button" class="icon-btn" aria-label="Remove" onClick=${() => {
                    draft.remove(r);
                    setOutcome(null);
                  }}><${Icon} name="x" /></button></td>
                </tr>
              `
            )}</tbody>
          </table>
          <button type="button" class="btn sm mt" onClick=${() => p.add()}>
            <${Icon} name="plus" /> Add a category</button>
        `}
      <${SaveOutcome} outcome=${outcome} draft=${draft} />
      <${FormError} error=${save.error} />
    </${Dialog}>
  `;
}
