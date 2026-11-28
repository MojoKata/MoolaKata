// A loan's parts of its account page (requirements S1.9): the summary on the Overview, the
// Schedule tab, the payment dialog that splits a payment by the schedule, the servicer's
// balance against the computed one, and the terms form shared by New account and Settings.
import { useEffect, useRef, useState } from 'preact/hooks';
import { canAdd, Record, whyNotAdd, whyRead } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { DraftDialog, RecField, saveNow, useDraft } from './draft-form.js';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date, money } from '../kit/format.js';
import { useFormats } from '../kit/formats.js';
import { Amt } from '../kit/amount.js';
import { Empty, Failed, Loading } from '../kit/bits.js';
import { openDialog } from '../kit/dialog.js';
import { useDialogGuide } from './help.js';
import { errAt, Field, FormError, Select, TypedInput } from '../kit/fields.js';
import { Icon } from '../kit/icon.js';
import { toast } from '../kit/toast.js';
import { CategoryField, useCategories } from './categories.js';
import { dec, num } from '../kit/dec.js';
import { Action, StatePill } from '../kit/state.js';
import { ACCEPT, ReceiptDialog, ReceiptLinkRec, uploadAll } from './receipt.js';

export const METHODS = /** @type {[string, string][]} */ ([
  ['amortized', 'Monthly amortization'],
  ['daily', 'Simple interest, daily'],
]);

/** How a payment day with none recorded reads (S1.9.3), by the Payments setting. */
const MODES = /** @type {{ [mode: string]: string }} */ ({
  recorded: 'Recorded here',
  assumed: 'Assumed as scheduled',
});

const POINTS = [['purchase', 'Buying the home'], ['refinance', 'A refinance']];

/** "2055-01-01" as "Jan 2055". */
const month = (/** @type {string} */ iso) => date(iso).replace(/ \d+,/, '');

const clean = (
  /** @type {any} */ s,
) => (s ? String(s).replace(/[$,%\s]/g, '').replace('−', '-') : '');

/** Whether a mortgage's points are typed. @param {LoanRec} r */
const hasPoints = (r) => r.get('points') != null;

/** Whether its payments count split by the schedule (S1.9.7.1). @param {LoanRec} r */
const isSplit = (r) => r.get('budgetCounting') === 'split';

/**
 * A split payment's parts as budgets count them (S1.9.7.1): the loan's field naming each one's
 * category, its label, the shipped category it starts in, and whether only a mortgage has it.
 */
const BUDGET_PARTS = /** @type {[string, string, string, boolean][]} */ ([
  ['interestCategoryId', 'Interest', 'loans.interest', false],
  ['escrowCategoryId', 'Escrow', 'loans.escrow', true],
  ['pmiCategoryId', 'PMI', 'loans.pmi', true],
  ['feesCategoryId', 'Fees', 'loans.fees', false],
  ['principalCategoryId', 'Principal', 'loans.principal', false],
]);

/** The shipped categories by their key. @param {any[]} list @returns {{ [key: string]: string }} */
const shippedOf = (list) =>
  Object.fromEntries(list.filter((c) => c.builtIn).map((c) => [c.builtIn, c.id]));

/** A loan's terms (S1.9), as the draft of New account or of its Settings edits them. */
export class LoanRec extends Record {
  /** @override */
  static prefix = 'Loan';
  /** @override */
  static fields = FIELDS.LoanRecord;
  /** @override */
  static defaults = {
    payment: null,
    escrowTax: null,
    escrowInsurance: null,
    pmi: null,
    drawMonths: null,
    resets: [],
    recasts: [],
    originalValue: null,
    points: null,
    pointsPaidOn: null,
    pointsPurpose: null,
    securedById: null,
    budgetCounting: 'split',
    budgetCategoryId: null,
    interestCategoryId: null,
    escrowCategoryId: null,
    pmiCategoryId: null,
    feesCategoryId: null,
    principalCategoryId: null,
    paymentsMode: null,
  };
  /** @override */
  static rules = {
    // A whole payment counts in the category chosen; split, by the schedule, each part in
    // the category named for it, kept while it counts whole (S1.9.7).
    budgetCategoryId: {
      when: (/** @type {LoanRec} */ r) => !isSplit(r),
      requiredWhen: (/** @type {LoanRec} */ r) => !isSplit(r),
    },
    ...Object.fromEntries(BUDGET_PARTS.map(([f]) => [f, { requiredWhen: isSplit }])),
    // Points come whole: the day paid and what they paid for, once an amount is typed (S1.9.6).
    pointsPaidOn: { when: hasPoints, requiredWhen: hasPoints },
    pointsPurpose: {
      when: hasPoints,
      requiredWhen: hasPoints,
      setWhen: (/** @type {LoanRec} */ r) => hasPoints(r) && r.get('pointsPurpose') == null,
      value: 'purchase',
    },
  };
}

/**
 * A new loan's terms, as its type usually has them: an auto loan over five years, simple
 * interest; a HELOC drawn for ten; its split's parts in the shipped categories (S1.9.7.1).
 * @param {string} type @param {string} accountId
 */
export async function newTerms(type, accountId) {
  const shipped = shippedOf(/** @type {any[]} */ ((await api.get('/categories')).items));
  return {
    accountId,
    termMonths: type === 'auto-loan' ? 60 : 360,
    method: type === 'auto-loan' ? 'daily' : 'amortized',
    drawMonths: type === 'heloc' ? 120 : null,
    ...Object.fromEntries(BUDGET_PARTS.map(([f, , key]) => [f, shipped[key] ?? null])),
  };
}

/**
 * The terms' fields, bound to the loan's record.
 * @param {{ rec: LoanRec, type: string }} p
 */
export function TermsFields({ rec, type }) {
  const mortgage = type === 'mortgage';
  return html`
    <div class="row">
      ${type === 'heloc'
        ? html`
          <${RecField} rec=${rec} name="principal" label="Original principal" min="0.00"
            format=${money} />
        `
        : html`
          <${RecField} rec=${rec} name="principal" label="Original principal" above=${0}
            format=${money} />
        `}
      <${RecField} rec=${rec} name="startDate" label="Start date" type="date" />
    </div>
    <div class="row">
      <${RecField} rec=${rec} name="termMonths" label="Term (months)" id="term-months"
        spin=${true} min=${1} max=${600} />
      <${RecField} rec=${rec} name="rate" label="Interest rate" kind="percent" atMost=${40}
        negative=${false} format=${(/** @type {any} */ n) => n + '%'} />
    </div>
    <div class="row">
      <${RecField} rec=${rec} name="method" label="Interest method" options=${METHODS} />
      <${RecField} rec=${rec} name="payment" label="Scheduled payment"
        placeholder="computed from the terms" />
    </div>
    ${mortgage
      ? html`
        <div class="row">
          <${RecField} rec=${rec} name="escrowTax" label="Property tax escrow per payment"
            id="escrow-tax" negative=${false} placeholder="none" />
          <${RecField} rec=${rec} name="escrowInsurance" label="Insurance escrow per payment"
            id="escrow-insurance" negative=${false} placeholder="none" />
        </div>
        <div class="row">
          <${RecField} rec=${rec} name="pmi" label="PMI per month" id="pmi" negative=${false}
            placeholder="none" />
          <${RecField} rec=${rec} name="points" label="Points paid" id="points" above=${0}
            placeholder="none" />
        </div>
        ${rec.applies('pointsPaidOn')
          ? html`
            <div class="row">
              <${RecField} rec=${rec} name="pointsPaidOn" label="Points paid on" type="date"
                id="points-paid-on" />
              <${RecField} rec=${rec} name="pointsPurpose" label="Points for" id="points-for"
                options=${POINTS} />
            </div>
          `
          : null}
      `
      : null}
    ${['mortgage', 'heloc', 'auto-loan', 'loan'].includes(type)
      ? html`<${SecuredBy} rec=${rec} type=${type} />`
      : null}
    ${type === 'heloc'
      ? html`
        <${RecField} rec=${rec} name="drawMonths" label="Draw period (months)" id="draw-months"
          spin=${true} min=${0} max=${Math.max(0, Number(rec.get('termMonths') || 600) - 1)} />
      `
      : null}
    <${InBudgets} rec=${rec} mortgage=${mortgage} />
  `;
}

/**
 * How the loan's payments count in budgets (S1.9.7): split by the schedule, each part in the
 * category the loan names for it (escrow and PMI a mortgage's alone), or whole in one
 * category. A blank is refused at Save, each offering its shipped one as its default (R3.11).
 * @param {{ rec: LoanRec, mortgage: boolean }} p
 */
function InBudgets({ rec, mortgage }) {
  const shipped = shippedOf(useCategories().list);
  const spent = (/** @type {any} */ c) => c.kind !== 'transfer';
  const parts = isSplit(rec) ? BUDGET_PARTS.filter(([, , , only]) => mortgage || !only) : [];
  return html`
    <div class="row">
      <${RecField} rec=${rec} name="budgetCounting" label="In budgets" id="in-budgets"
        options=${[
          ['split', 'Split by the schedule'],
          ['whole', 'The whole payment in one category'],
        ]} />
      ${rec.applies('budgetCategoryId')
        ? html`
          <${CategoryField} rec=${rec} name="budgetCategoryId" label="Counts in"
            id="budget-category" first=${['', 'Choose a category']} only=${spent}
            reset=${shipped.loans} />
        `
        : null}
    </div>
    ${pairs(parts).map((row) =>
      html`
        <div class="row">
          ${row.map(([f, label, key]) =>
            html`
              <${CategoryField} rec=${rec} name=${f} label=${label}
                id=${f.replace('CategoryId', '-category')} first=${['', 'Choose a category']}
                only=${f === 'principalCategoryId'
                  ? (/** @type {any} */ c) => c.kind === 'savings'
                  : spent} reset=${shipped[key]} />
            `
          )}
        </div>
      `
    )}
  `;
}

/** A list two to a row. @template T @param {T[]} xs @returns {T[][]} */
function pairs(xs) {
  const out = [];
  for (let i = 0; i < xs.length; i += 2) out.push(xs.slice(i, i + 2));
  return out;
}

/**
 * The item the loan is secured by (S1.9.5: a home, a vehicle or any other), and a mortgage's
 * original home value.
 * @param {{ rec: LoanRec, type: string }} p
 */
function SecuredBy({ rec, type }) {
  const res = useList('/items');
  const items = /** @type {any[]} */ (res.data) || [];
  return html`
    <div class="row">
      <${RecField} rec=${rec} name="securedById" label="Secured by" id="secured-by"
        options=${[
          ['', items.length ? 'Nothing' : 'Nothing yet: add the item first'],
          ...items.map((i) => [i.id, `${i.name} · ${i.accountName}`]),
        ]} />
      ${type === 'mortgage'
        ? html`
          <${RecField} rec=${rec} name="originalValue" label="Home's original value"
            id="original-value" placeholder="the home's cost then" />
        `
        : null}
    </div>
  `;
}

/** @param {{ a: any, reload: () => void }} p */
export function LoanSummary({ a, reload }) {
  const res = useApi(`/accounts/${a.id}/loan`, {}, ['import']);
  const v = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} lines=${4} />`;
  const again = () => {
    res.reload();
    reload();
  };
  if (!v.terms) {
    return html`
      <div class="card">
        <h3>Loan</h3>
        <${Empty} action=${html`<a class="btn sm" href=${`/ui/accounts/${a.id}/settings`}>Settings</a>`}>No terms yet</${Empty}></div>
    `;
  }
  const t = v.terms;
  const s = v.servicer;
  return html`
    <div class="card facts">
      <h3>Loan<span class="spacer"></span><${Action} class="btn sm"
      why=${whyNotAdd('Txn', a)} onClick=${() =>
        openDialog(PaymentDialog, { a, v }).then((ok) => ok && again())}><${Icon}
        name="plus" /> Record a Payment</${Action}></h3>
      <div class="list-item"><span class="grow dim">Owed</span><${Amt} v=${v.balance} /></div>
      <div class="list-item"><span class="grow dim">Rate</span>${String(dec(v.rate))}% ${t
          .resets.length
        ? 'adjustable'
        : 'fixed'}<span class="small dim">${'\u00a0'}· ${METHODS.find(([k]) => k === t.method)?.[1]
        .toLowerCase()}</span></div>
      <div class="list-item"><span class="grow dim">Payment</span><span><${Amt} v=${v
        .payment} />${dec(v.total).gt(dec(v.payment))
        ? html`<span class="small dim"> · <${Amt} v=${v.total} /> with escrow</span>`
        : null}${v.interestOnlyUntil
        ? html`<div class="small dim">interest only until ${date(v.interestOnlyUntil)}</div>`
        : null}</span></div>
      <div class="list-item"><span class="grow dim">Next due</span>${v.nextDate
        ? date(v.nextDate)
        : '—'}</div>
      ${v.missed
        ? html`
          <div class="list-item" id="loan-missed"><span class="grow dim">Missed</span><span><span
                class="pill bad">${v.missed} ${v.missed === 1
                  ? 'payment'
                  : 'payments'}</span>${' '}<span class="small down"><${Amt} v=${v
                  .overdue} /> overdue</span></span></div>
        `
        : null}
      <div class="list-item"><span class="grow dim">Paid off</span><span>${v.payoffDate
        ? month(v.payoffDate)
        : '—'}${v.originalPayoff && v.originalPayoff !== v.payoffDate
        ? html`<span class="small dim"> · scheduled ${month(v.originalPayoff)}</span>`
        : null}</span></div>
      <div class="list-item"><span class="grow dim">Interest paid</span><${Amt} v=${v
        .interestPaid} /></div>
      <div class="list-item"><span class="grow dim">Interest still to pay</span><${Amt} v=${v
        .interestAhead} cents=${false} /></div>
      <div class="list-item"><span class="grow dim">Principal this year</span><${Amt} v=${v
        .principalThisYear} /></div>
      ${num(v.overpaid)
        ? html`<div class="list-item"><span class="grow dim">Overpaid</span><${Amt} v=${v.overpaid} /></div>`
        : null}
      ${v.following
        ? html`
          <div
            class="list-item"><span class="grow dim">Following</span><span>${v.following
              .name}<span class=${'small ' +
              (dec(v.following.ahead).isNegative() ? 'down' : 'up')}> · ${dec(
                v.following.ahead,
              ).isNegative()
              ? 'behind'
              : 'ahead'} by <${Amt} v=${dec(v.following.ahead).abs()} /></span></span></div>
        `
        : null}
      ${v.equity
        ? html`
          <div
            class="list-item"><span class="grow dim">Equity in ${v.equity
              .itemName}</span><span><${Amt} v=${v.equity.equity} cents=${false} /><span
                    class="small dim"> · LTV ${String(v.equity.ltv)}%</span></span></div>
                    ${v.equity.pmiRequest || v.equity.pmiEnds
                      ? html`
                        <div
                          class="list-item"><span class="grow dim">PMI</span><span class="small">${v
                              .equity.pmiRequest
                            ? `can be dropped on request from ${date(v.equity.pmiRequest)}`
                            : ''}${v.equity.pmiRequest && v.equity.pmiEnds
                            ? '; '
                            : ''}${v.equity.pmiEnds
                            ? `ends by itself ${date(v.equity.pmiEnds)}`
                            : ''}</span></div>
                      `
                      : null}
        `
        : null}
      <div class="list-item"><span class="grow dim">Servicer's balance</span>${s
        ? html`<span><${Amt} v=${s.servicer} /> on ${date(s.date)} ${
          dec(s.difference).isZero()
            ? html`<span class="pill ok"><${Icon} name="check" /> matches</span>`
            : html`<span class="pill warn">off by <${Amt} v=${s.difference} signed /></span>`
        }</span>`
        : html`<span class="dim">not typed</span>`}${'\u00a0'}<${Action} class="btn sm"
        why=${whyNotAdd('Anchr', a)} onClick=${() =>
          openDialog(ServicerDialog, { a }).then((ok) => ok && again())}>Type It</${Action}></div>
    </div>
    ${a.access.writable ? html`<${Candidates} a=${a} again=${again} />` : null}
    <${LeftOut} a=${a} again=${again} />
  `;
}

/**
 * The rows an import left out, dated before the loan starts (S1.9.3): kept until the start is
 * moved on or before them and they are added, or left out for good. Seen by whoever reads the
 * loan; its fixes need write on it.
 * @param {{ a: any, again: () => void }} p
 */
function LeftOut({ a, again }) {
  const res = useList(`/accounts/${a.id}/imports`, {}, ['import']);
  const kept = (/** @type {any[]} */ (res.data) || []).filter((i) => i.leftOut);
  if (!kept.length) return null;
  const done = () => {
    res.reload();
    again();
  };
  return html`
    <div class="card"><h3>Left Out of Imports</h3>
      ${kept.map((i) => html`<${KeptRows} key=${i.id} a=${a} i=${i} done=${done} />`)}
    </div>
  `;
}

/** A row an import left out (S1.9.3): added by its import's route, or deleted by a save. */
class LeftOutRec extends Record {
  /** @override */
  static prefix = 'ImpLO';
  /** @override */
  static fields = FIELDS.LeftOutRecord;
}

/**
 * Leave Them Out: every row the path lists (an import's rows left out) deleted in one save.
 * @param {string} path
 */
export async function leaveOut(path) {
  const page = /** @type {any} */ (await api.get(path));
  await saveNow((d) => {
    for (const x of page.items) d.remove(d.load(LeftOutRec, x));
  });
}

/**
 * One import's rows left out, with Move the Start, Add Them (those the start now lets in) and
 * Leave Them Out.
 * @param {{ a: any, i: any, done: () => void }} p
 */
function KeptRows({ a, i, done }) {
  const res = useList(`/imports/${i.id}/left-out`, {}, ['import']);
  const rows = /** @type {any[]} */ (res.data) || [];
  const act = useSubmit(async (/** @type {boolean} */ add) => {
    if (add) {
      const ids = rows.filter((x) => x.fits).map((x) => x.id);
      await api.post(`/imports/${i.id}/left-out`, { rows: ids });
      toast(`${ids.length === 1 ? '1 row' : ids.length + ' rows'} added`);
    } else {
      await leaveOut(`/imports/${i.id}/left-out`);
      toast('Left out');
    }
    res.reload();
    done();
  });
  if (!rows.length) return null;
  const why = whyRead(a);
  return html`
    <div class="small dim">${i.fileName} · imported ${date(i.createdAt.slice(0, 10))}</div>
    ${rows.map((x) =>
      html`<div class="list-item"><div class="grow">${x.payee || 'Row'}<div
        class="small dim">${date(x.date)}${x.fits ? ' · on or after the start now' : ''}</div></div>
        <${Amt} v=${x.amount} />${
        x.fits ? null : html`<${StatePill} tone="warn" why=${x.reason}>Before start</${StatePill}>`
      }</div>`
    )}
    <div
      class="toolbar mt">${why
        ? html`<${Action} class="btn sm" why=${why}>Move the Start</${Action}>`
        : html`<a class="btn sm" href=${`/ui/accounts/${a.id}/settings`}>Move the Start</a>`}<${Action} class="btn sm" why=${why ||
        (rows.some((x) => x.fits)
          ? null
          : 'Dated before the loan starts: move the start first')} disabled=${act
        .busy} onClick=${() =>
        act.run(true).catch((/** @type {any} */ e) =>
          toast(e.message)
        )}>Add Them</${Action}><${Action}
      class="btn sm" why=${why} disabled=${act.busy} onClick=${() =>
        act.run(false).catch((/** @type {any} */ e) =>
          toast(e.message)
        )}>Leave Them Out</${Action}></div>
  `;
}

/** Bank transactions that look like this loan's payment, to link with one click. */
/** @param {{ a: any, again: () => void }} p */
function Candidates({ a, again }) {
  const res = useList(`/accounts/${a.id}/loan/candidates`, {}, ['import']);
  const rows = /** @type {any[]} */ (res.data) || [];
  // The payment on the loan made and paired with the bank's transaction (S1.9.3).
  const link = useSubmit(async (/** @type {any} */ c) => {
    if (c.pairWith) {
      // The payment is on the loan already: the two become one transfer, nothing new made.
      await saveNow((d) => {
        const loan = d.load(PayTxn, { ...c.pairWith, accountId: a.id, transferWithId: null });
        loan.set('kind', 'transfer');
        loan.set('transferWithId', c.transactionId);
      });
      toast('Paired with the payment already recorded');
      res.reload();
      again();
      return;
    }
    const split = await splitOf(a, c.date, c.amount);
    await saveNow((d) => {
      const loan = d.add(PayTxn, { accountId: a.id, date: c.date, amount: c.amount });
      fillPayment(d, a, loan, { parts: {} }, { pairedWith: c.transactionId, split });
    });
    toast('Linked and split by the schedule');
    res.reload();
    again();
  });
  if (!rows.length) return null;
  return html`
    <div class="card"><h3>Looks like a Payment</h3>
      ${rows.map((c) =>
        html`<div class="list-item"><div class="grow">${c.payee || 'Payment'}<div
          class="small dim">${c.accountName} · ${date(c.date)}${
          c.pairWith ? html`${' '}· pair with the payment of ${date(c.pairWith.date)}` : null
        }</div></div><${Amt} v=${c.amount} /><button class="btn sm" disabled=${link.busy} onClick=${() =>
          link.run(c).catch(() => {})}>${c.pairWith ? 'Pair' : 'Link'}</button></div>`
      )}
    </div>
  `;
}

/** @param {{ a: any }} p */
export function Schedule({ a }) {
  const res = useApi(`/accounts/${a.id}/loan`, {}, ['import']);
  const [all, setAll] = useState(false);
  const v = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} />`;
  if (!v.terms) {
    return html`<${Empty} action=${html`<a class="btn sm" href=${`/ui/accounts/${a.id}/settings`}>Settings</a>`}>No terms yet</${Empty}>`;
  }
  const escrow = v.rows.some((/** @type {any} */ r) => num(r.escrow) || num(r.pmi));
  const firstAhead = v.rows.findIndex((/** @type {any} */ r) => !r.past);
  const from = Math.max(0, (firstAhead < 0 ? v.rows.length : firstAhead) - 3);
  const shown = all ? v.rows : v.rows.slice(from, from + 15);
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <div class="table-wrap">
        <table class="t">
          <caption class="sr-only">Amortization schedule</caption>
          <thead>
            <tr><th>Due</th><th class="num">Payment</th><th class="num">Principal</th>
          <th class="num">Interest</th>${escrow
            ? html`<th class="num">Escrow and PMI</th>`
            : null}<th class="num">Extra</th><th class="num">Balance</th></tr>
          </thead>
          <tbody>${shown.map((/** @type {any} */ r) =>
            html`<tr class=${r.past && r.status !== 'missed' ? 'dim' : ''}><td style=${{
              whiteSpace: 'nowrap',
            }}>${date(r.date)}${r.past ? html`${' '}<${RowPill} status=${r.status} />` : null}</td>
            <td class="num"><${Amt} v=${r.payment} /></td><td class="num"><${Amt} v=${r.principal} /></td><td class="num"><${Amt} v=${r.interest} /></td>${
              escrow
                ? html`
                  <td class="num">
                    <${Amt} v=${dec(r.escrow).add(dec(r.pmi))} />
                  </td>
                `
                : null
            }<td class="num">${
              num(r.overpayment)
                ? html`<${Amt} v=${r.overpayment} />`
                : html`<span class="dim">—</span>`
            }</td><td class="num"><${Amt} v=${r.balance} /></td></tr>`
          )}</tbody>
        </table>
      </div>
      <div class="toolbar"
        style=${{ padding: '0 8px' }}><span class="small dim">${v.rows
          .length} payments</span><span class="spacer"></span><button class="btn sm"
          onClick=${() => setAll(!all)}>${all ? 'Show Fewer' : 'Show All'}</button></div>
    </div>
  `;
}

/**
 * A past row's state (S1.9.3): paid as recorded, assumed as scheduled, or missed.
 * @param {{ status: string }} p
 */
function RowPill({ status }) {
  if (status === 'missed') return html`<span class="pill bad">missed</span>`;
  if (status === 'assumed') {
    return html`
      <${StatePill} tone="info"
        why="No payment is recorded for it: it is assumed paid as scheduled.">assumed</${StatePill}>
    `;
  }
  return html`<span class="pill ok">paid</span>`;
}

const PARTS = /** @type {[string, string][]} */ ([
  ['principal', 'Principal'],
  ['interest', 'Interest'],
  ['escrowTax', 'Escrow: property tax'],
  ['escrowInsurance', 'Escrow: insurance'],
  ['pmi', 'PMI'],
  ['fees', 'Fees'],
]);

/** A payment's transaction, on the loan or its bank half, as the payment's draft makes it. */
class PayTxn extends Record {
  /** @override */
  static prefix = 'Txn';
  /** @override */
  static fields = FIELDS.TxnRecord;
  /** @override */
  static defaults = { payee: 'Payment', transferWithId: null };
}

/** A part of a payment (S1.9.3): a split of its transaction, in the part's category. */
class PayPart extends Record {
  /** @override */
  static prefix = 'Split';
  /** @override */
  static fields = FIELDS.SplitRecord;
  /** @override */
  static defaults = { memo: null, reimbursable: null, owedBy: null };
  /** @override */
  static ownedBy = ['transactionId'];
}

/** How the schedule splits a payment of this amount on this day, each part's category with it. */
const splitOf = (/** @type {any} */ a, /** @type {string} */ day, /** @type {string} */ amount) =>
  api.get(`/accounts/${a.id}/loan/split`, { date: day, amount });

/**
 * The payment's records put into its draft (S1.9.3): the loan's transaction, its bank half
 * from `from` (or the bank transaction `pairedWith`), and a split for each part not zero.
 * Made once and changed after, so a question confirmed stays with its record.
 * @param {import('../app/draft.js').Draft} draft @param {any} a @param {PayTxn} loan
 * @param {{ bank?: PayTxn, parts: { [k: string]: PayPart } }} own
 * @param {{ from?: string, pairedWith?: string, split: any }} o
 */
function fillPayment(draft, a, loan, own, { from, pairedWith, split }) {
  const amount = clean(loan.get('amount'));
  if (from) {
    own.bank ||= draft.add(PayTxn, { kind: 'transfer', payee: a.name });
    if (own.bank.removed) draft.unremove(own.bank);
    own.bank.set('accountId', from);
    own.bank.set('date', loan.get('date'));
    own.bank.set('amount', amount ? String(dec(amount).neg()) : null);
  } else if (own.bank && !own.bank.removed) draft.remove(own.bank);
  const other = from ? own.bank?.id : pairedWith;
  loan.set('kind', other ? 'transfer' : 'deposit');
  loan.set('transferWithId', other || null);
  for (const [k] of PARTS) {
    const v = clean(split[k]);
    let r = own.parts[k];
    if (v && !dec(v).isZero()) {
      r ||= own.parts[k] = draft.add(PayPart, {
        transactionId: loan.id,
        categoryId: split.categories[k] ?? null,
      });
      if (r.removed) draft.unremove(r);
      r.set('amount', v);
    } else if (r && !r.removed) draft.remove(r);
  }
}

/** @param {{ close: (v?: any) => void, a: any, v: any }} p */
export function PaymentDialog({ close, a, v }) {
  const fmt = useFormats();
  useDialogGuide('dialog-loan-payment');
  const accounts = useList('/accounts');
  const banks = (/** @type {any[]} */ (accounts.data) || []).filter((x) =>
    x.group === 'banking' && !x.closedOn && canAdd('Txn', x)
  );
  const f = useDraft((draft) => {
    draft.add(PayTxn, { accountId: a.id, date: v.nextDate || fmt.today(), amount: v.total });
  }, [a.id]);
  const loan = /** @type {PayTxn | undefined} */ (f.draft?.records[0]);
  const own = useRef(new WeakMap());
  const [from, setFrom] = useState('');
  // The schedule's split, read again as the day or the amount changes; shown on asking.
  const [split, setSplit] = useState(/** @type {any} */ (null));
  const [shown, setShown] = useState(false);
  const [typed, setTyped] = useState(false);
  const [failed, setFailed] = useState(/** @type {any} */ (null));
  const day = loan?.get('date');
  const amount = clean(loan?.get('amount'));
  useEffect(() => {
    setSplit(null);
    setShown(false);
    setTyped(false);
    setFailed(null);
    if (!day || !amount || !(Number(amount) > 0)) return;
    let gone = false;
    splitOf(a, day, amount).then((s) => !gone && setSplit(s), (e) => !gone && setFailed(e));
    return () => {
      gone = true;
    };
  }, [day, amount]);
  // The bank's half already there, when the payment was imported first (S1.7): the
  // payment pairs with it rather than recording it again.
  const [half, setHalf] = useState(/** @type {any} */ (null));
  useEffect(() => {
    setHalf(null);
    if (!from || !day || !amount || !(Number(amount) > 0)) return;
    let gone = false;
    api.get(`/accounts/${a.id}/loan/halves`, { account: from, date: day, amount }).then(
      (/** @type {any} */ r) => !gone && setHalf(r.items[0] || null),
      () => {},
    );
    return () => {
      gone = true;
    };
  }, [from, day, amount]);
  const before = () => {
    if (!f.draft || !loan || !split) return false;
    if (!own.current.has(f.draft)) own.current.set(f.draft, { parts: {} });
    fillPayment(
      f.draft,
      a,
      loan,
      own.current.get(f.draft),
      half ? { pairedWith: half.transactionId, split } : { from, split },
    );
  };
  const e = failed;
  return html`
    <${DraftDialog} f=${f} title="Record a Payment" close=${close} what="This payment"
      label="Record" done="Payment recorded and split" before=${before}
      disabled=${!split}>
      ${loan
        ? html`
          <div class="row">
            <${RecField} rec=${loan} name="date" label="Paid on" id="paid-on" type="date" />
            <${RecField} rec=${loan} name="amount" label="Amount" id="amount" />
          </div>
          <${Field} label="From account" id="from-account">
            <${Select} value=${from} onChange=${setFrom} options=${[
              ['', 'None'],
              ...banks.map((b) => [b.id, b.name]),
            ]} /></${Field}>
          ${half
            ? html`
              <div
                class="notice">${half.accountName} already holds this payment (${date(
                  half.date,
                )}, <${Amt} v=${half.amount} />): it is paired with it, not recorded again.</div>
            `
            : null}
          <div class="toolbar"><span class="spacer"></span><button type="button" class="btn sm" disabled=${!split}
              onClick=${() => setShown(true)}>Show the Split</button></div>
          ${shown && split
            ? html`<div class="row" style=${{ flexWrap: 'wrap' }}>${
              PARTS.map(([k, label]) =>
                html`
                  <${Field} label=${label} id=${'part-' + k} help="split"
                    error=${typed ? errAt(e, k) : null}>
                    <${TypedInput} kind="money" value=${split[k]} onInput=${(
                      /** @type {string} */ x,
                    ) => {
                      setSplit({ ...split, [k]: x });
                      setTyped(true);
                    }} />
                    </${Field}>
                `
              )
            }</div>`
            : null}
          ${e ? html`<${FormError} error=${e} />` : null}
        `
        : null}
    </${DraftDialog}>
  `;
}

/** A balance typed from the institution's site (S1.11.2), as its dialog's draft makes it. */
export class AnchorRec extends Record {
  /** @override */
  static prefix = 'Anchr';
  /** @override */
  static fields = FIELDS.AnchorRecord;
  /** @override */
  static defaults = { note: null };
}

/** @param {{ close: (v?: any) => void, a: any }} p */
function ServicerDialog({ close, a }) {
  const fmt = useFormats();
  useDialogGuide('dialog-servicer-balance');
  // Typed as the principal owed; kept as the loan's balance, below zero.
  const [owed, setOwed] = useState('');
  const f = useDraft((draft) => {
    draft.add(AnchorRec, { accountId: a.id, date: fmt.today() });
  }, [a.id]);
  const rec = f.draft?.records[0];
  return html`
    <${DraftDialog} f=${f} title="Type the Servicer's Balance" close=${close}
      what="This balance" label="Check" done="Balance recorded and checked">
      ${rec
        ? html`
          <div class="row">
            <${Field} label="Principal owed" id="owed" error=${rec.error('balance')}>
              <${TypedInput} kind="money" value=${owed} onInput=${(/** @type {string} */ v) => {
                setOwed(v);
                rec.input('balance', v.trim() ? '-' + v.trim().replace(/^[-−]/, '') : '');
              }} />
              </${Field}>
              <${RecField} rec=${rec} name="date" label="As of" id="as-of" type="date" />
              </div>
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * The Settings card with the terms, in the account's Settings draft: the schedule is worked
 * out again once they are saved.
 * @param {{ a: any, rec: LoanRec }} p
 */
export function TermsCard({ a, rec }) {
  const res = useApi(`/accounts/${a.id}/loan`);
  const v = /** @type {any} */ (res.data);
  return html`
    <div class="card"><h3>Loan Terms</h3>
      <${TermsFields} rec=${rec} type=${a.type} />
      <${RecField} rec=${rec} name="paymentsMode" label="Payments" id="payments-mode"
        options=${[
          [
            '',
            v?.paymentsAutomatic
              ? `Automatic: ${MODES[v.paymentsAutomatic].toLowerCase()}`
              : 'Automatic',
          ],
          ...Object.entries(MODES),
        ]} />
      <${Dated} rec=${rec} name="resets" label="Rate resets" what="rate" add="Add a reset"
        none="No rate resets" />
      <${Dated} rec=${rec} name="recasts" label="Recasts" what="fee" add="Add a recast"
        none="No recasts" />
      ${v?.terms
        ? html`<p class="small dim">Computed payment <${Amt} v=${v.terms.computedPayment} />.</p>`
        : null}
    </div>
  `;
}

/**
 * Dated rows of the terms: an ARM's resets (date, rate) or recasts (date, fee), a list field
 * of the loan's record. `none` is the empty line while it has none.
 * @param {{ rec: LoanRec, name: string, label: string, what: string, add: string,
 *   none: string }} p
 */
function Dated({ rec, name, label, what, add, none }) {
  const key = what === 'rate' ? 'rate-resets' : 'recasts';
  const rows = /** @type {any[]} */ (rec.get(name) || []);
  const set = (/** @type {any[]} */ next) => rec.set(name, next);
  const put = (/** @type {number} */ i, /** @type {string} */ k, /** @type {string} */ x) =>
    set(rows.map((r, j) => (j === i ? { ...r, [k]: k === 'date' ? x : clean(x) } : r)));
  return html`
    <div class="mt"><div class="toolbar"><b class="small" data-help=${key}>${label}</b><span
      class="spacer"></span><button type="button" class="btn sm" onClick=${() =>
        set([...rows, { date: '', [what]: '0' }])}><${Icon} name="plus" /> ${add}</button></div>
      ${rows.length ? null : html`<${Empty}>${none}</${Empty}>`}
      ${rows.map((r, i) =>
        html`
          <div class="row">
            <${Field} label="From" help=${key} id=${`${what}-date-${i}`}>
              <${TypedInput} kind="date" value=${r.date} onInput=${(/** @type {string} */ x) =>
                put(i, 'date', x)} />
              </${Field}>
              <${Field} label=${what === 'rate' ? 'Rate' : 'Fee'} help=${key} id=${`${what}-${i}`}>
                <${TypedInput} kind=${what === 'rate' ? 'percent' : 'money'}
                  value=${r[what] == null ? '' : String(r[what])}
                  onInput=${(/** @type {string} */ x) => put(i, what, x)} />
                </${Field}>
                <button type="button" class="icon-btn" aria-label="Remove"
                  onClick=${() => set(rows.filter((_, j) => j !== i))}><${Icon} name="x" /></button>
                </div>
        `
      )}
    </div>
  `;
}

/** The tooltip of the Documents card's upload button. */
const ADD_DOCUMENT = 'Upload and attach a loan document';

/**
 * A loan's documents other than its statements (S9.3): a closing disclosure, a note. Each is a
 * receipt kept on the loan's account, uploaded or attached from the inbox here, and detached
 * again; kept until the loan is paid off, then the statements' period (S14.10.1.2).
 * @param {{ a: any }} p
 */
export function LoanDocuments({ a }) {
  const docs = useList(`/accounts/${a.id}/documents`, {}, ['receipt']);
  const inbox = useList('/receipts', { show: 'inbox' }, ['receipt']);
  const [busy, setBusy] = useState(false);
  const why = whyRead(a);
  const rows = /** @type {any[]} */ (docs.data) || [];
  const free = /** @type {any[]} */ (inbox.data) || [];
  /** Each receipt kept on the loan, saved at once. @param {string[]} ids */
  const keep = async (ids) => {
    await saveNow((draft) => {
      for (const id of ids) {
        draft.add(ReceiptLinkRec, { receiptId: id, kind: 'account', itemId: a.id });
      }
    });
    docs.reload();
    inbox.reload();
  };
  const failed = (/** @type {any} */ e) => toast(e.message);
  const send = async (/** @type {FileList} */ files) => {
    setBusy(true);
    try {
      const made = await uploadAll(files);
      await keep(made.map((r) => r.id));
      toast(made.length === 1 ? 'Document kept' : `${made.length} documents kept`);
    } catch (e) {
      failed(e);
    } finally {
      setBusy(false);
    }
  };
  const detach = async (/** @type {any} */ r) => {
    const ln = r.links.find((/** @type {any} */ l) =>
      l.kind === 'account' && l.itemId === a.id && !l.statement
    );
    if (!ln) return;
    await saveNow((draft) => {
      const x = draft.load(ReceiptLinkRec, {
        id: ln.id,
        version: ln.version,
        receiptId: r.id,
        kind: 'account',
        itemId: a.id,
      });
      draft.remove(x);
    }).then(() => {
      toast('Document detached');
      docs.reload();
      inbox.reload();
    }, failed);
  };
  return html`
    <div class="card mt"><h3 data-help="documents">Documents</h3>
      ${docs.error
        ? html`<${Failed} error=${docs.error} retry=${docs.reload} />`
        : !docs.data
        ? html`<${Loading} lines=${2} />`
        : rows.length
        ? rows.map((r) =>
          html`
            <div class="list-item"><span class="grow"><button type="button" class="link-btn"
              onClick=${() => openDialog(ReceiptDialog, { id: r.id }).then(docs.reload)}><${Icon}
              name="clip" /> ${r.fileName}</button></span><${Action}
              class="icon-btn" why=${why} aria-label=${'Detach ' + r.fileName}
              onClick=${() => detach(r)}><${Icon} name="x" /></${Action}></div>
          `
        )
        : html`<${Empty}>No documents yet</${Empty}>`}
      <div class="toolbar mt">
        ${why
          ? html`
            <${Action} class="btn sm" why=${why}><${Icon} name="upload" /> Add Document</${Action}>
          `
          : html`
            <label class="btn sm" for="f-loan-files" data-tip=${ADD_DOCUMENT}><${Icon}
              name="upload" /> ${busy ? 'Uploading…' : 'Add Document'}</label><input
              id="f-loan-files" class="sr-only" type="file" multiple
              accept=${ACCEPT} data-help="documents" onChange=${(/** @type {any} */ e) => {
                send(e.currentTarget.files);
                e.currentTarget.value = '';
              }} />
          `}
        <${Select} id="f-attach-document" aria-label="Attach from the inbox"
          data-help="documents" disabled=${!!why || !free.length}
          value="" options=${[
            ['', free.length ? 'Attach from the inbox…' : 'The inbox is empty'],
            ...free.map((r) => [r.id, r.fileName]),
          ]} onChange=${(/** @type {string} */ v) => {
            if (v) keep([v]).then(() => toast('Document kept'), failed);
          }} />
      </div>
    </div>
  `;
}
