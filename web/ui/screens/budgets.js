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
import { errAt, Field, FormError, Input, Select, Switch } from '../components/fields.js';
import { toast } from '../components/toast.js';
import { ShareDialog } from '../components/share.js';
import { BarChart, FlowChart } from '../charts/chart.js';
import { dec, num } from '../app/dec.js';
import { TransactionDialog } from './transaction-dialog.js';

const TABS = /** @type {[string, string][]} */ ([
  ['month', 'This month'],
  ['cash-flow', 'Cash flow'],
  ['trends', 'Trends'],
  ['recurring', 'Recurring'],
]);

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
    openDialog(BudgetDialog, {}).then((b) => {
      if (b) {
        list.reload();
        location.assign(`/ui/budgets/${b.id}/month`);
      }
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
          html`<option value=${x.id}>${x.name}${
            x.level === 'owner' ? '' : ` (${x.ownerName})`
          }</option>`
        )}
      </select>
      <span class="spacer"></span>
      <button type="button" class="btn"
        onClick=${newBudget}><${Icon} name="plus" /> New budget</button>
    </div>
    <${Tabs} tabs=${TABS} current=${current} base=${`/ui/budgets/${b.id}`} />
    ${current === 'month'
      ? html`<${ThisMonth} b=${b} month=${shown.value} reloadList=${list.reload} />`
      : current === 'cash-flow'
      ? html`<${CashFlow} b=${b} month=${shown.value} />`
      : current === 'trends'
      ? html`<${Trends} b=${b} month=${shown.value} />`
      : html`<${Recurring} b=${b} />`}
  `;
}

/** @param {{ b: any, month: string, reloadList: () => void }} p */
function ThisMonth({ b, month, reloadList }) {
  const res = useApi(`/budgets/${b.id}/month`, { month }, ['import', 'share']);
  const v = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} lines=${6} />`;
  const spend = v.rows.filter((/** @type {any} */ r) => r.kind === 'expense');
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
  const edit = () =>
    openDialog(PlanDialog, { b, month, rows: v.rows, version: v.version }).then((x) =>
      x && res.reload()
    );
  return html`
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
        <div class="delta dim">of ${money(v.plannedSpending, { cents: false })} planned · ${money(
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
    <div class="card mt"><h3>Categories<span class="spacer"></span>
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
        ? html`<button type="button" class="btn sm" onClick=${edit}>Edit plan</button>`
        : null}</h3>
      ${spend.length
        ? spend.map((/** @type {any} */ r) => html`<${BudgetRow} r=${r} />`)
        : html`<p class="small dim">Nothing planned for this month yet.${
          v.canWrite
            ? html`
              <button type="button" class="linklike" onClick=${edit}>Plan it</button>
            `
            : ''
        }</p>`}
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

/** @param {{ r: any }} p */
function BudgetRow({ r }) {
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
          : null}${num(
            r.carried,
          )
          ? html`<div class="dim">${dec(r.carried).gt(0) ? '+' : '−'}${
            money(
              dec(r.carried).abs(),
              { cents: false },
            )
          } rolled over</div>`
          : null}</div>
    </div>
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

/** A new budget: its name and the accounts it covers. @param {{ close: (v?: any) => void }} p */
function BudgetDialog({ close }) {
  useDialogGuide('dialog-budget');
  const accounts = useList('/accounts');
  const [name, setName] = useState('');
  const [ids, setIds] = useState(/** @type {Set<string>} */ (new Set()));
  const outside = useList('/budgets/left-out', { accountIds: [...ids].sort() });
  const left = /** @type {any[]} */ (outside.data) || [];
  const save = useSubmit(async () => {
    const out = await api.post('/budgets', { name, accountIds: [...ids] }, { idempotent: true });
    toast('Budget made: plan its categories next');
    close(out);
  });
  const list = /** @type {any[]} */ (accounts.data) || [];
  return html`
    <${Dialog} title="New budget" close=${close} onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Save</button>`}>
      <${Field} label="Name" error=${errAt(save.error, 'name')}>
        <${Input} value=${name} onInput=${setName} placeholder="Household" required />
        </${Field}>
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
        ${errAt(save.error, 'accountIds')
          ? html`<div class="err">${errAt(save.error, 'accountIds')}</div>`
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
        <${FormError} error=${save.error} shown=${['name', 'accountIds']} />
        </${Dialog}>
  `;
}

/**
 * The plan from the month shown on: a line per category, monthly or yearly, rolling over or
 * not. Earlier months keep the plan they had.
 * @param {{ close: (v?: any) => void, b: any, month: string, rows: any[], version: number }} p
 */
function PlanDialog({ close, b, month, rows, version }) {
  useDialogGuide('dialog-plan');
  const cats = useList('/categories');
  const [lines, setLines] = useState(
    rows.map((r) => ({
      categoryId: r.categoryId,
      amount: String(dec(r.planned).sub(dec(r.carried))),
      cadence: r.cadence,
      rollover: r.rollover,
    })),
  );
  const save = useSubmit(async () => {
    await api.put(`/budgets/${b.id}/plan`, {
      month: month + '-01',
      lines: lines.filter((l) => l.categoryId).map((l) => ({
        ...l,
        amount: String(l.amount || '0').trim(),
      })),
    }, version);
    toast('Plan saved');
    close(true);
  });
  const options = /** @type {[string, string][]} */ ([
    ['', 'Choose a category'],
    ...(/** @type {any[]} */ (cats.data) || []).filter((c) => c.kind !== 'transfer').map((
      c,
    ) => [c.id, c.path]),
  ]);
  const set = (/** @type {number} */ i, /** @type {string} */ k) => (/** @type {any} */ v) =>
    setLines(lines.map((l, j) => (i === j ? { ...l, [k]: v } : l)));
  return html`
    <${Dialog} title=${`Plan from ${monthLabel(month)}`} wide close=${close}
      onSubmit=${() => save.run().catch(() => {})}
      note="Earlier months keep the plan they had."
      footer=${html`<button class="btn primary" disabled=${save.busy}>Save</button>`}>
      <table class="t plan">
        <thead>
          <tr>
            <th>Category</th>
            <th class="num">Amount</th>
            <th>Every</th>
            <th>Rollover</th>
            <th></th>
          </tr>
        </thead>
        <tbody>${lines.map((l, i) =>
          html`
            <tr>
              <td>
                <${Select} value=${l.categoryId} onChange=${set(i, 'categoryId')} options=${options}
                  aria-label="Category" data-help="category" />
              </td>
              <td class="num">
                <${Input} value=${l.amount} onInput=${set(i, 'amount')} inputmode="decimal"
                  aria-label="Amount" data-help="amount" bad=${errAt(
                    save.error,
                    `lines.${i}.amount`,
                  )} />
              </td>
              <td>
                <${Select} value=${l.cadence} onChange=${set(i, 'cadence')}
                  options=${[['month', 'Month'], [
                    'year',
                    'Year',
                  ]]} aria-label="Every" data-help="every" />
              </td>
              <td>
                <${Switch} on=${l.rollover} onChange=${set(i, 'rollover')} label="Rollover"
                  help="rollover" disabled=${l.cadence === 'year'} />
              </td>
              <td><button type="button" class="icon-btn" aria-label="Remove" onClick=${() =>
                setLines(lines.filter((_, j) => j !== i))}><${Icon} name="x" /></button></td>
            </tr>
          `
        )}</tbody>
      </table>
      <button type="button" class="btn sm mt" onClick=${() =>
        setLines([...lines, { categoryId: '', amount: '', cadence: 'month', rollover: false }])}>
        <${Icon} name="plus" /> Add a category</button>
      <${FormError} error=${save.error} />
      </${Dialog}>
  `;
}
