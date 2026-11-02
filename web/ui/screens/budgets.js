// Budgets (requirements S7.1–S7.5): a month's categories as progress bars, income against
// spending, cash flow, a category's trend, and the recurring transactions, for one budget at a
// time. A household budget is one shared with a group at write.
import { signal } from '@preact/signals';
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date, money, today } from '../app/format.js';
import { useTitle } from '../components/frame.js';
import { useDialogGuide, useGuide } from '../components/help.js';
import { Empty, Failed, Loading, Tabs } from '../components/bits.js';
import { Icon } from '../components/icon.js';
import { Dialog, openDialog } from '../components/dialog.js';
import { errAt, Field, FormError, Input, Select, SwitchRow } from '../components/fields.js';
import { toast } from '../components/toast.js';
import { ShareDialog } from '../components/share.js';
import { BarChart, FlowChart } from '../charts/chart.js';
import { Dec, dec, num } from '../app/dec.js';
import { canAdd, Record } from '../app/draft.js';
import {
  DraftDialog,
  RecField,
  RowErrors,
  saveNow,
  saveOne,
  useDraft,
} from '../components/draft-form.js';
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
          html`<option value=${x.id}>${x.name}${x.access.mine ? '' : ` (${x.ownerName})`}${
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
  // The Spent card (S7.3.12): spending against the monthly lines and outside the plan, of what
  // those lines had available; yearly lines are compared with their year, named beside.
  const left = dec(v.left);
  const spentInMonth = dec(v.available).sub(left);
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
  const canMove = b.moves && canAdd('BdgMv', b);
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
    await saveNow((d) => d.remove(d.load(MoveRec, { ...m, budgetId: b.id })));
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
            <div class="value amt">${money(spentInMonth.toString(), {
              cents: false,
            })}</div>
            <div
              class="delta dim">of ${money(v.available, {
                cents: false,
              })} available · ${money(
                left.abs(),
                { cents: false },
              )} ${left.isNegative() ? 'over' : 'left'}${v.daysLeft
                ? `, ${v.daysLeft} day${v.daysLeft === 1 ? '' : 's'} to go`
                : ''}${dec(v.yearlySpent).gt(0)
                ? ` · and ${money(v.yearlySpent, { cents: false })} against yearly lines`
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
      <span class="small dim" style=${{ fontWeight: 400 }}>${b.access.mine
        ? b.sharedWith ? `shared with ${b.sharedWith}` : 'yours'
        : `${b.ownerName}'s · ${b.access.writable ? 'write' : 'read'}`}</span>
      ${b.access.shareable
        ? html`<button type="button" class="btn sm" onClick=${() =>
          openDialog(ShareDialog, { kind: 'budget', id: b.id, name: b.name }).then(
            reloadList,
          )}><${Icon} name="share" /> Share</button>`
        : null}
      ${b.access.writable
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
          b.access.writable
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
                  ${b.access.writable
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
  const write = b.access.writable;
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
            : 's'}${x.reserves ? ' · reserves' : ''}${x.moves ? ' · moves' : ''} · ${x.access.mine
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

/** The user's own record, as Make active sets the budget they follow (S7.12.1). */
class FollowRec extends Record {
  /** @override */
  static prefix = 'User';
  /** @override */
  static fields = FIELDS.UserRecord;
}

/**
 * Make a budget the one the user follows (S7.12.1): nothing is rewritten.
 * @param {{ close: (v?: any) => void, b: any, from?: any }} p
 */
function MakeActiveDialog({ close, b, from }) {
  useDialogGuide('dialog-make-active');
  const save = useSubmit(async () => {
    const me = await api.get('/profile');
    const was = { id: me.id, version: me.version, activeBudgetId: me.activeBudgetId };
    await saveOne(FollowRec, was, { activeBudgetId: b.id });
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
  const start = to || planned.find((r) => r.state === 'over')?.categoryId || '';
  const f = useDraft((draft) => {
    const over = planned.find((r) => r.categoryId === start);
    const card = cards.find((x) => 'card:' + x.accountId === start);
    const mv = draft.add(MoveRec, {
      budgetId: b.id,
      month: month + '-01',
      fromCategoryId: sources[0]?.categoryId || null,
      toCategoryId: start && !start.startsWith('card:') ? start : null,
      cardId: start.startsWith('card:') ? start.slice(5) : null,
      note: null,
    });
    const amount = card
      ? card.notBacked
      : over && over.state === 'over'
      ? dec(over.remaining).abs()
      : null;
    if (amount != null) mv.set('amount', Dec.of(amount));
  }, []);
  const rec = /** @type {MoveRec | undefined} */ (f.draft?.records[0]);
  const from = rec?.get('fromCategoryId') || '';
  const dest = rec?.get('cardId') ? 'card:' + rec.get('cardId') : rec?.get('toCategoryId') || '';
  const label = (/** @type {any} */ r) =>
    `${r.label}${r.target ? ' (reserve)' : ''}: ${money(left(r).abs())} ${
      left(r).isNegative() ? 'over' : 'left'
    }`;
  return html`
    <${DraftDialog} f=${f} title=${`Move money: ${monthLabel(month)}`} close=${close}
      what="This move" label="Move" done="Moved">
      ${rec
        ? html`
          <div class="row">
            <${Field} label="From" error=${rec.error('fromCategoryId')}>
              <${Select} value=${from} onChange=${(/** @type {string} */ v) =>
                rec.set('fromCategoryId', v || null)} options=${[
                ...(envelope ? [['', 'To Budget']] : []),
                ...sources.map((r) => [r.categoryId, label(r)]),
              ]} />
              </${Field}>
              <${Field} label="To" error=${rec.error('toCategoryId') || rec.error('cardId')}>
                <${Select} value=${dest} onChange=${(/** @type {string} */ v) => {
                  rec.set('toCategoryId', v && !v.startsWith('card:') ? v : null);
                  rec.set('cardId', v.startsWith('card:') ? v.slice(5) : null);
                }} options=${[
                  ...(envelope ? [['', 'To Budget']] : [['', 'Choose a category']]),
                  ...planned.filter((r) => r.categoryId !== from).map((r) => [
                    r.categoryId,
                    label(r),
                  ]),
                  ...cards.map((x) => [
                    'card:' + x.accountId,
                    `${x.name}'s payment: ${money(x.notBacked)} not backed`,
                  ]),
                ]} />
                </${Field}>
                </div>
                <${RecField} rec=${rec} name="amount" label="Amount to move" />
                <${RecField} rec=${rec} name="note" label="Note" placeholder="optional" />
                <p class="small dim">For ${monthLabel(month)} only. It shows on both rows and in
            Activity; delete it to undo.</p>
        `
        : null}
    </${DraftDialog}>
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
  // A transfer in kept as the account's own: a move to no category (S7.10.4).
  const keepOwn = async (/** @type {any} */ x) => {
    try {
      await saveNow((d) =>
        d.add(LandedRec, {
          budgetId: b.id,
          month: x.date,
          transactionId: x.transactionId,
          amount: String(x.amount),
        })
      );
      toast("Kept as the account's own");
      res.reload();
    } catch (e) {
      toast(/** @type {any} */ (e).message);
    }
  };
  const assign = (/** @type {any} */ h, /** @type {any} */ x) =>
    openDialog(AssignDialog, { b, h, landed: x }).then((y) => y && res.reload());
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
 * Landed money given as a move (S7.10.5): to a reserve held where it landed, or to no
 * category, kept as the account's own. Its month is the transaction's.
 */
class LandedRec extends Record {
  /** @override */
  static prefix = 'BdgMv';
  /** @override */
  static fields = FIELDS.MoveRecord;
  /** @override */
  static defaults = { fromCategoryId: null, toCategoryId: null, cardId: null, note: null };
}

/**
 * An amount spread among reserves by their balances, the last taking what rounding leaves;
 * evenly when none has a balance.
 * @param {string} amount @param {any[]} reserves @returns {string[]}
 */
function spreadByBalance(amount, reserves) {
  const weights = reserves.map((r) => (dec(r.balance).gt(0) ? dec(r.balance) : dec(0)));
  const total = Dec.sum(weights);
  let left = dec(amount);
  return reserves.map((_, i) => {
    if (i === reserves.length - 1) return String(left);
    const share = total.isZero()
      ? dec(amount).div(reserves.length, 2)
      : dec(amount).mul(weights[i]).div(total, 2);
    left = left.sub(share);
    return String(share);
  });
}

/** Whether a line gives nothing: empty, or zero. @param {any} v */
const nothing = (v) => {
  try {
    return v == null || v === '' || dec(v).isZero();
  } catch {
    return false;
  }
};

/**
 * Landed money given to the reserves held where it landed, a line each, or kept as the
 * account's own (S7.10.5): a move for each line given something, saved together.
 * @param {{ close: (v?: any) => void, b: any, h: any, landed: any }} p
 */
function AssignDialog({ close, b, h, landed }) {
  useDialogGuide('dialog-assign');
  const free = String(landed.free);
  const f = useDraft((draft) => {
    const base = { budgetId: b.id, month: landed.date, transactionId: landed.transactionId };
    const shares = spreadByBalance(free, h.reserves);
    h.reserves.forEach((/** @type {any} */ r, /** @type {number} */ i) =>
      draft.add(LandedRec, { ...base, toCategoryId: r.categoryId, amount: shares[i] })
    );
    draft.add(LandedRec, { ...base, toCategoryId: null, amount: '0' });
  }, [landed.transactionId]);
  const lines = /** @type {LandedRec[]} */ (f.draft?.records || []);
  const spread = () => {
    const shares = spreadByBalance(free, h.reserves);
    lines.forEach((r, i) => r.set('amount', i < shares.length ? shares[i] : '0'));
  };
  // A line given nothing makes no move.
  const before = () => {
    for (const r of lines) {
      if (nothing(r.get('amount'))) {
        if (!r.removed) f.draft?.remove(r);
      } else if (r.removed) f.draft?.unremove(r);
    }
    if (lines.every((r) => r.removed)) return false;
  };
  let given = dec(0);
  for (const r of lines) {
    try {
      given = given.add(dec(r.get('amount') || 0));
    } catch { /* typed, not yet a number */ }
  }
  return html`
    <${DraftDialog} f=${f} title="Assign landed money" close=${close} what="This assignment"
      label="Assign" done="Assigned" before=${before}>
      <p style=${{ marginTop: 0 }}>${money(landed.amount)} ${landed.payee || 'landed'} in ${h
        .accountName} on ${date(landed.date)}. In the budget it counts as it always does; this
        says whose it is.</p>
      ${lines.length
        ? html`
          ${h.reserves.map((/** @type {any} */ r, /** @type {number} */ i) =>
            html`
              <${RecField} rec=${lines[i]} name="amount" label=${r.label}
                id=${'assign-' + r.categoryId} help="reserve" />
            `
          )}
          <${RecField} rec=${lines[lines.length - 1]} name="amount"
            label="Kept as the account's own" id="assign-own" help="own" />
          <div
            class="toolbar"><span class="small dim">${money(String(given))} of ${money(
              free,
            )} given; the rest stays unassigned.</span><span class="spacer"></span><button
            type="button" class="btn sm" onClick=${spread}>Spread by balance</button></div>
        `
        : null}
    </${DraftDialog}>
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

/** A deposit paired with spending it pays back (S2.9.2): made, or deleted to unpair. */
class PairRec extends Record {
  /** @override */
  static prefix = 'Rmbrs';
  /** @override */
  static fields = FIELDS.PairIn;
}

/**
 * Pair a deposit with spending awaiting being paid back.
 * @param {{ close: (v?: any) => void, item: any }} p
 */
function PairDialog({ close, item }) {
  useDialogGuide('dialog-pair');
  // The most a deposit pays back: what is awaited, or what is left of it.
  const most = (/** @type {any} */ o) =>
    o ? (dec(o.free).lt(dec(item.awaited)) ? o.free : item.awaited) : item.awaited;
  const f = useDraft((draft) => {
    const first = item.offers[0];
    const r = draft.add(PairRec, {
      spendingId: item.spendingId,
      splitId: item.splitId,
      paybackId: first?.transactionId || null,
    });
    r.set('amount', Dec.of(most(first)));
  }, []);
  const rec = /** @type {PairRec | undefined} */ (f.draft?.records[0]);
  const pick = rec?.get('paybackId');
  return html`
    <${DraftDialog} f=${f} title="Pair a payback" close=${close} what="This pairing"
      label="Pair" done="Paired: that much is paid back" disabled=${!pick}>
      <p style=${{ marginTop: 0 }}>${item.payee || 'Spending'}, ${date(item.date)}: ${money(
        item.awaited,
      )} awaited${item.owedBy ? ` from ${item.owedBy}` : ''}.</p>
      ${rec
        ? html`
          <fieldset class="field" style=${{ border: 0, padding: 0, margin: '0 0 14px' }}>
            <legend class="small" style=${{
              color: 'var(--fg-dim)',
            }}>Deposits that may pay it back</legend>
            ${item.offers.map((/** @type {any} */ o) =>
              html`<label class="list-item" style=${{ cursor: 'pointer' }}><input type="radio"
                name="payback" data-help="deposits" checked=${o.transactionId === pick}
                onChange=${() => {
                rec.set('paybackId', o.transactionId);
                rec.set('amount', Dec.of(most(o)));
              }} /><span class="grow">${o.payee || 'A deposit'}<div class="small dim">${
                date(o.date)
              } · ${o.accountName}</div></span><span class="amt">${money(o.free)}</span></label>`
            )}
            ${rec.error('paybackId')
              ? html`<div class="err">${rec.error('paybackId')}</div>`
              : null}
          </fieldset>
          <${RecField} rec=${rec} name="amount" label="Pays back"
            hint="All of it, or part; one deposit can pay back several." />
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * The accounts a budget covers, with a note naming those it leaves out that often get transfers
 * from them (S7.3.2).
 * @param {{ ids: Set<string>, setIds: (s: Set<string>) => void, error?: string | null }} p
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
      ${error ? html`<div class="err">${error}</div>` : null}
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
 * Each account is a record of its own, counted from the budget's start (S7.1.7).
 * @param {{ close: (v?: any) => void }} p
 */
function BudgetDialog({ close }) {
  useDialogGuide('dialog-budget');
  const [estimate, setEstimate] = useState('6');
  const f = useDraft((draft) => {
    draft.add(BudgetRec, { name: '', method: 'tracking', reserves: true, moves: true });
  }, []);
  const rec = /** @type {BudgetRec | undefined} */ (f.draft?.records[0]);
  const counted = /** @type {any[]} */ (f.draft?.records || []).filter((r) =>
    r instanceof BudgetAccountRec && !r.removed
  );
  const setIds = (/** @type {Set<string>} */ v) => {
    if (!f.draft || !rec) return;
    for (const r of counted) if (!v.has(r.get('accountId'))) f.draft.remove(r);
    const have = new Set(counted.map((r) => r.get('accountId')));
    for (const id of v) {
      if (!have.has(id)) f.draft.add(BudgetAccountRec, { budgetId: rec.id, accountId: id });
    }
  };
  return html`
    <${DraftDialog} f=${f} title="New budget" wide close=${close} what="This budget"
      label="Make it" saved=${(/** @type {any} */ o) => {
        toast('Budget made');
        close({ ...o.saved[0].record, estimate: Number(estimate) || 0 });
      }}>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="name" label="Name" placeholder="Household" />
          <${RecField} rec=${rec} name="method" label="Method" options=${METHODS}
            hint="It keeps its method; copy it as a scenario to try the other." />
          <${RecField} rec=${rec} name="reserves" label="Reserves"
            hint="Save toward a target in a category, month by month." />
          <${RecField} rec=${rec} name="moves" label="Moves" disabled=${rec.get('method') ===
            'envelope'} hint=${rec.get('method') === 'envelope'
            ? 'Always on in an envelope budget.'
            : 'Cover one category from another for a month.'} />
          <${AccountsPicker} ids=${new Set(counted.map((r) => r.get('accountId')))}
            setIds=${setIds} error=${counted.map((r) => r.error('accountId')).find(Boolean)} />
          <${Field} label="Estimate from history"
            hint="A plan line per category from its average; you keep, change or drop each.">
            <${Select} value=${estimate} onChange=${setEstimate} options=${[
              ['0', "Don't estimate"],
              ['3', 'The last 3 months'],
              ['6', 'The last 6 months'],
              ['12', 'The last 12 months'],
            ]} />
            </${Field}>
        `
        : null}
    </${DraftDialog}>
  `;
}

/** The first day of the month `n` months from `m` (YYYY-MM-DD). @param {string} m @param {number} n */
function addMonths(m, n) {
  const d = new Date(Number(m.slice(0, 4)), Number(m.slice(5, 7)) - 1 + n, 1);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`;
}

/**
 * The months a change to a budget's accounts can count from: since the budget began, or one
 * of the last twelve months, this one first.
 * @param {string} thisMonth
 * @returns {[string, string][]}
 */
function fromChoices(thisMonth) {
  /** @type {[string, string][]} */
  const out = [];
  for (let i = 0; i < 12; i++) {
    const m = addMonths(thisMonth, -i);
    const name = new Date(m + 'T12:00:00').toLocaleDateString('en-US', {
      month: 'long',
      year: 'numeric',
    });
    out.push([m, i === 0 ? `${name} (this month)` : name]);
  }
  out.push(['start', 'Since the budget began']);
  return out;
}

/**
 * A budget's name, options and accounts, and where its money comes from (S7.1.6). Its accounts
 * are records over months (S7.1.7): one added counts from the month chosen, one taken out ends
 * the month before it, so earlier months keep what they counted (R3.10).
 * @param {{ close: (v?: any) => void, b: any }} p
 */
function BudgetSettingsDialog({ close, b }) {
  useDialogGuide('dialog-budget-settings');
  const accounts = useList('/accounts');
  const list = /** @type {any[]} */ (accounts.data) || [];
  const byId = Object.fromEntries(list.map((a) => [a.id, a]));
  const thisMonth = today().slice(0, 7) + '-01';
  const [from, setFrom] = useState(thisMonth);
  // The accounts ticked or unticked here, applied to the records from the month chosen.
  const [wanted, setWanted] = useState(/** @type {Set<string> | null} */ (null));
  const f = useDraft(async (draft) => {
    const [x, rows] = await Promise.all([
      api.get(`/budgets/${b.id}`),
      api.get(`/budgets/${b.id}/accounts`),
    ]);
    draft.load(BudgetRec, x);
    for (const r of rows.items) draft.load(BudgetAccountRec, r);
  }, [b.id]);
  const rec = /** @type {BudgetRec | undefined} */ (f.draft?.records[0]);
  const rows =
    /** @type {BudgetAccountRec[]} */ ((f.draft?.records || []).filter((r) =>
      r instanceof BudgetAccountRec
    ));
  // An account's open record: the one still counting, or made here.
  const open = (/** @type {string} */ id) =>
    rows.find((r) => r.get('accountId') === id && !r.removed && !r.get('untilMonth')) ||
    rows.find((r) => r.get('accountId') === id && r.state === 'new' && !r.removed) || null;
  const counting = new Set(
    rows.filter((r) => r.state !== 'new' && !r.get('untilMonth')).map((r) => r.get('accountId')),
  );
  const ids = wanted || counting;
  /** @param {Set<string>} next @param {string} month */
  const apply = (next, month) => {
    const draft = f.draft;
    if (!draft || !rec) return;
    const first = month === 'start' ? null : month;
    for (const r of rows) {
      if (r.state === 'new') draft.remove(r);
      else {
        if (r.removed) draft.unremove(r);
        r.revert('untilMonth');
      }
    }
    for (const r of rows) {
      const id = r.get('accountId');
      if (r.state === 'new' || r.get('untilMonth') || next.has(id)) continue;
      // Taken out: never counted, when it began then or later; else it ends the month before.
      if (!first || (r.get('fromMonth') && r.get('fromMonth') >= first)) draft.remove(r);
      else r.set('untilMonth', addMonths(first, -1));
    }
    for (const id of next) {
      if (!counting.has(id)) {
        draft.add(BudgetAccountRec, { budgetId: rec.id, accountId: id, fromMonth: first });
      }
    }
  };
  const inBudget = [...ids].map((x) => byId[x]).filter(Boolean);
  const learned = Object.fromEntries(b.roles.map((/** @type {any} */ r) => [r.accountId, r]));
  // What a budget covers is a setting (S7.1): its accounts.
  const owner = b.access.configurable;
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
    open(id)?.set(k, v || null);
  const changedAccounts = wanted !== null &&
    (wanted.size !== counting.size || [...wanted].some((x) => !counting.has(x)));
  return html`
    <${DraftDialog} f=${f} title=${`${b.name}: settings`} wide close=${close} what="This budget"
      done="Saved" note=${`${
        b.method === 'envelope' ? 'An envelope' : 'A tracking'
      } budget: it keeps its method.`}>
      ${rec
        ? html`
          <${RecField} rec=${rec} name="name" label="Name" />
          <${RecField} rec=${rec} name="reserves" label="Reserves"
            hint="Save toward a target in a category, month by month." />
          <${RecField} rec=${rec} name="moves" label="Moves" disabled=${b.method === 'envelope'}
            hint=${b.method === 'envelope'
              ? 'Always on in an envelope budget.'
              : 'Cover one category from another for a month.'} />
          ${owner
            ? html`
              <${AccountsPicker} ids=${ids} setIds=${(/** @type {Set<string>} */ v) => {
                setWanted(v);
                apply(v, from);
              }} error=${rows.map((r) => r.error('fromMonth') || r.error('accountId')).find(
                Boolean,
              )} />
              ${changedAccounts
                ? html`
                  <${Field} label="The change counts from"
                    hint="Months before it keep the accounts they had.">
                    <${Select} value=${from} options=${fromChoices(thisMonth)}
                      data-help="counts-from" onChange=${(/** @type {string} */ v) => {
                        setFrom(v);
                        apply(ids, v);
                      }} />
                    </${Field}>
                `
                : null}
            `
            : null}
          <fieldset class="field" style=${{ border: 0, padding: 0, margin: '0 0 14px' }}>
            <legend class="small" style=${{ color: 'var(--fg-dim)' }}>Where money comes
              from</legend>
            ${[
              ...inBudget.filter((a) => a.type === 'credit-card'),
              ...inBudget.filter((a) => a.type !== 'credit-card'),
            ].map((a) =>
              a.type === 'credit-card'
                ? html`<div class="list-item"><span class="grow">${a.name}<div class="small dim"
                  >paid from</div></span><${Select} value=${open(a.id)?.get('paidFromId') || ''}
                  onChange=${set(a.id, 'paidFromId')} options=${choices(a, 'paidFromId')}
                  aria-label=${`${a.name}: paid from`} data-help="paid-from" /></div>`
                : ['savings', 'money-market'].includes(a.type)
                ? html`<div class="list-item"><span class="grow">${a.name}<div class="small dim"
                  >money for its reserves moves from</div></span><${Select}
                  value=${open(a.id)?.get('movedFromId') || ''} onChange=${
                  set(
                    a.id,
                    'movedFromId',
                  )
                } options=${choices(a, 'movedFromId')} aria-label=${`${a.name}: moved from`}
                  data-help="moved-from" /></div>`
                : null
            )}
            ${rows.map((r) => r.error('paidFromId') || r.error('movedFromId')).find(Boolean)
              ? html`<div class="err">${
                rows.map((r) => r.error('paidFromId') || r.error('movedFromId')).find(Boolean)
              }</div>`
              : null}
          </fieldset>
        `
        : null}
    </${DraftDialog}>
  `;
}

/** A budget (S7.1), as its dialogs' drafts edit it. */
class BudgetRec extends Record {
  /** @override */
  static prefix = 'Bdgt';
  /** @override */
  static fields = FIELDS.BudgetRecord;
  /** @override */
  static rules = {
    // An envelope budget always has moves (S7.1.4).
    moves: {
      setWhen: (/** @type {BudgetRec} */ r) => r.get('method') === 'envelope' && !r.get('moves'),
      value: true,
    },
  };
}

/** An account a budget counts, over months (S7.1.7), with its roles (S7.1.6). */
class BudgetAccountRec extends Record {
  /** @override */
  static prefix = 'BdgAc';
  /** @override */
  static fields = FIELDS.BudgetAccountRecord;
  /** @override */
  static ownedBy = ['budgetId'];
}

/** A move between categories for a month (S7.11): made, or deleted to undo it. */
class MoveRec extends Record {
  /** @override */
  static prefix = 'BdgMv';
  /** @override */
  static fields = FIELDS.MoveRecord;
}

/**
 * A plan line as a dialog's draft edits it (S7.1.2, S12.15): stored as it was read, changed
 * from the month the dialog plans from, and taken out (`out`) from then; an amount of 0 keeps
 * it in the plan, putting nothing in.
 */
class PlanLine extends Record {
  /** @override */
  static prefix = 'BdgLn';
  /** @override */
  static fields = FIELDS.LineIn;
  /** @override */
  static defaults = {
    amount: Dec.parse('0.00'),
    out: false,
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
    out: true,
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
  const f = useDraft(async (draft) => {
    const p = await api.get(`/budgets/${b.id}/plan`, { month });
    for (const ln of p.lines) draft.load(PlanLine, ln);
  }, [b.id, month]);
  const cats = useList('/categories');
  const kinds = Object.fromEntries(
    (/** @type {any[]} */ (cats.data) || []).map((c) => [c.id, c.kind]),
  );
  const paths = Object.fromEntries(
    (/** @type {any[]} */ (cats.data) || []).map((c) => [c.id, c.path]),
  );
  const draft = f.draft;
  if (draft) {
    for (const r of /** @type {PlanLine[]} */ (draft.records)) {
      r.asOf = month + '-01';
      r.reserves = !!b.reserves;
      r.kinds = kinds;
    }
  }
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
  return { f, draft, add, kinds, paths, cats };
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
  // The proposals chosen, put into the plan's draft as it saves: an existing line takes the
  // amount and cadence, and keeps the rest of what it has (its target, where it is held).
  const apply = () => {
    const draft = p.draft;
    if (!draft) return false;
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
    <${DraftDialog} f=${p.f} title="Plan from history" wide close=${close} changed=${changed}
      before=${apply} what="The plan" done="Plan saved" label="Save the plan"
      disabled=${!found.length} note="Nothing is saved until you save.">
      <${Field} label="Months to average" id="months">
        <${Select} value=${span} onChange=${(/** @type {string} */ v) => setSpan(v)} options=${[
          ['3', 'The last 3 months'],
          ['6', 'The last 6 months'],
          ['12', 'The last 12 months'],
        ]} /></${Field}>
      ${res.error
        ? html`<${Failed} error=${res.error} />`
        : !res.data
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
                    }} /></td>
                  <td>${x.label}</td>
                  <td class="num">
                    <${Input} value=${amounts[x.categoryId] ?? money(x.amount).slice(1)}
                      onInput=${(/** @type {string} */ v) =>
                        setAmounts({ ...amounts, [x.categoryId]: v })}
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
    </${DraftDialog}>
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
  const span = 6 + (envelope ? 1 : 0) + (b.reserves ? 2 : 0);
  // A line added and left without a category is no line.
  const before = () => {
    for (const r of rows) if (r.state === 'new' && !r.get('categoryId')) draft?.remove(r);
  };
  return html`
    <${DraftDialog} f=${p.f} title=${`Plan from ${monthLabel(month)}`} wide close=${close}
      before=${before} what="The plan" done="Plan saved"
      note="Earlier months keep the plan they had. $0 pauses a line and keeps what it holds; ✕ takes it out.">
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
                  <${RecField} rec=${r} name="categoryId" bare label="Category" help="category"
                    options=${options.filter(([id]) =>
                      !id || id === r.get('categoryId') || !taken.has(id)
                    )} />
                `
                : p.paths[r.get('categoryId')] || 'A category'}</td>
              <td class="num">
                <${RecField} rec=${r} name="amount" bare label="Amount" help="amount" />
              </td>
              <td>
                <${RecField} rec=${r} name="cadence" bare label="Every" help="every"
                  options=${[['month', 'Month'], ['year', 'Year']]} />
              </td>
              <td>
                <${RecField} rec=${r} name="rollover" bare label="Rollover" help="rollover"
                  disabled=${r.get('cadence') === 'year'} />
              </td>
              ${envelope
                ? html`
                  <td>
                    <${RecField} rec=${r} name="overspend" bare label="Overspent"
                      help="overspent" options=${[
                        ['carry', 'Carried negative'],
                        ['next', "From next month's To Budget"],
                      ]} />
                  </td>
                `
                : null}
              ${b.reserves
                ? html`
                  <td class="num">
                    <${RecField} rec=${r} name="target" bare label="Target" help="target"
                      placeholder="none" style=${{ width: '90px', textAlign: 'right' }} />
                  </td>
                  <td>
                    <${RecField} rec=${r} name="heldInId" bare label="Held in" help="held-in"
                      options=${heldOptions} />
                  </td>
                `
                : null}
              <td>
                <${RecField} rec=${r} name="projectionId" bare label="Projection"
                  help="projection" options=${plans} />
              </td>
              <td><button type="button" class="icon-btn" aria-label="Remove" onClick=${() =>
                draft?.remove(r)}><${Icon} name="x" /></button></td>
            </tr>
            <${RowErrors} rec=${r} span=${span} />
          `
        )}</tbody>
      </table>
      <button type="button" class="btn sm mt" onClick=${() => p.add()}>
        <${Icon} name="plus" /> Add a category</button>
      </${DraftDialog}>
  `;
}
