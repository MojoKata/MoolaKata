// A loan's parts of its account page (requirements S1.9): the summary on the Overview, the
// Schedule tab, the payment dialog that splits a payment by the schedule, the servicer's
// balance against the computed one, and the terms form shared by New account and Settings.
import { useState } from 'preact/hooks';
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { RecField } from './draft-form.js';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date, today } from '../app/format.js';
import { Amt } from './amount.js';
import { Empty, Failed, Loading } from './bits.js';
import { Dialog, openDialog } from './dialog.js';
import { useDialogGuide } from './help.js';
import { errAt, Field, FormError, Input, Select } from './fields.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';
import { dec, num } from '../app/dec.js';

export const METHODS = /** @type {[string, string][]} */ ([
  ['amortized', 'Monthly amortization'],
  ['daily', 'Simple interest, daily'],
]);

/** "2055-01-01" as "Jan 2055". */
const month = (/** @type {string} */ iso) => date(iso).replace(/ \d+,/, '');

const clean = (
  /** @type {any} */ s,
) => (s ? String(s).replace(/[$,%\s]/g, '').replace('−', '-') : '');

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
    securedById: null,
    budgetCounting: 'split',
    budgetCategoryId: null,
  };
  /** @override */
  static rules = {
    // A whole payment counts in the category chosen; split, by the schedule (S1.9.7).
    budgetCategoryId: { when: (/** @type {LoanRec} */ r) => r.get('budgetCounting') === 'whole' },
  };
}

/**
 * A new loan's terms, as its type usually has them: an auto loan over five years, simple
 * interest; a HELOC drawn for ten.
 * @param {string} type @param {string} accountId
 */
export function newTerms(type, accountId) {
  return {
    accountId,
    termMonths: type === 'auto-loan' ? 60 : 360,
    method: type === 'auto-loan' ? 'daily' : 'amortized',
    drawMonths: type === 'heloc' ? 120 : null,
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
      <${RecField} rec=${rec} name="principal" label="Original principal"
        placeholder=${type === 'heloc' ? '0' : '360,000'} />
      <${RecField} rec=${rec} name="startDate" label="Start date" type="date" />
    </div>
    <div class="row">
      <${RecField} rec=${rec} name="termMonths" label="Term (months)" id="term-months" />
      <${RecField} rec=${rec} name="rate" label="Interest rate" placeholder="5.875%" />
    </div>
    <div class="row">
      <${RecField} rec=${rec} name="method" label="Interest method" options=${METHODS} />
      <${RecField} rec=${rec} name="payment" label="Scheduled payment"
        hint="Blank: computed from the terms." />
    </div>
    ${mortgage
      ? html`
        <div class="row">
          <${RecField} rec=${rec} name="escrowTax" label="Escrow for property tax"
            id="escrow-tax" placeholder="per payment" />
          <${RecField} rec=${rec} name="escrowInsurance" label="Escrow for insurance"
            id="escrow-insurance" placeholder="per payment" />
        </div>
        <${RecField} rec=${rec} name="pmi" label="PMI per month" id="pmi" placeholder="0" />
      `
      : null}
    ${['mortgage', 'heloc', 'auto-loan', 'loan'].includes(type)
      ? html`<${SecuredBy} rec=${rec} type=${type} />`
      : null}
    ${type === 'heloc'
      ? html`
        <${RecField} rec=${rec} name="drawMonths" label="Draw period (months)" id="draw-months"
          hint="Interest only while drawing; then the balance is repaid over the rest of the term." />
      `
      : null}
    <${InBudgets} rec=${rec} />
  `;
}

/**
 * How the loan's payments count in budgets (S1.9.7): split by the schedule, or whole in one
 * category.
 * @param {{ rec: LoanRec }} p
 */
function InBudgets({ rec }) {
  const cats = useList('/categories');
  const list = /** @type {any[]} */ (cats.data) || [];
  return html`
    <div class="row">
      <${RecField} rec=${rec} name="budgetCounting" label="In budgets" id="in-budgets"
        hint="Counted at the bank account a payment comes from." options=${[
          ['split', 'Split by the schedule'],
          ['whole', 'The whole payment in one category'],
        ]} />
      <${RecField} rec=${rec} name="budgetCategoryId" label="Counts in" id="budget-category"
        options=${[
          ['', 'Loan payments'],
          ...list.filter((c) => c.kind !== 'transfer').map((c) => [c.id, c.path]),
        ]} />
    </div>
  `;
}

/**
 * The property or vehicle the loan is secured by, and a mortgage's original home value.
 * @param {{ rec: LoanRec, type: string }} p
 */
function SecuredBy({ rec, type }) {
  const res = useList('/items');
  const items = /** @type {any[]} */ (res.data) || [];
  return html`
    <div class="row">
      <${RecField} rec=${rec} name="securedById" label="Secured by" id="secured-by"
        hint="A property or vehicle, for the equity and loan-to-value." options=${[
          ['', items.length ? 'Nothing' : 'Nothing yet: add the property or vehicle first'],
          ...items.map((i) => [i.id, `${i.name} · ${i.accountName}`]),
        ]} />
      ${type === 'mortgage'
        ? html`
          <${RecField} rec=${rec} name="originalValue" label="Home's original value"
            id="original-value" hint="The appraisal or price when the loan was made." />
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
        <${Empty}>No terms yet. Set them in Settings to compute the schedule.</${Empty}></div>
    `;
  }
  const t = v.terms;
  const s = v.servicer;
  return html`
    <div class="card facts"><h3>Loan<span class="spacer"></span>${v.canWrite
      ? html`<button class="btn sm" onClick=${() =>
        openDialog(PaymentDialog, { a, v }).then((ok) => ok && again())}><${Icon}
          name="plus" /> Record a payment</button>`
      : null}</h3>
      <div class="list-item"><span class="grow dim">Owed</span><${Amt} v=${v.balance} /></div>
      <div class="list-item"><span class="grow dim">Rate</span>${String(dec(v.rate))}% ${t
          .resets.length
        ? 'adjustable'
        : 'fixed'}<span class="small dim">${'\u00a0'}· ${METHODS.find(([k]) => k === t.method)?.[1]
        .toLowerCase()}</span></div>
      <div class="list-item"><span class="grow dim">Payment</span><span><${Amt} v=${v
        .payment} />${dec(v.total).gt(dec(v.payment))
        ? html`<span class="small dim"> · <${Amt} v=${v.total} /> with escrow</span>`
        : null}</span></div>
      <div class="list-item"><span class="grow dim">Next due</span>${v.nextDate
        ? date(v.nextDate)
        : '—'}</div>
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
        : html`<span class="dim">not typed</span>`}${v.canWrite
        ? html`${'\u00a0'}<button class="btn sm" onClick=${() =>
          openDialog(ServicerDialog, { a }).then((ok) => ok && again())}>Type it</button>`
        : null}</div>
    </div>
    ${v.canWrite ? html`<${Candidates} a=${a} again=${again} />` : null}
  `;
}

/** Bank transactions that look like this loan's payment, to link with one click. */
/** @param {{ a: any, again: () => void }} p */
function Candidates({ a, again }) {
  const res = useList(`/accounts/${a.id}/loan/candidates`, {}, ['import']);
  const rows = /** @type {any[]} */ (res.data) || [];
  const link = useSubmit(async (/** @type {any} */ c) => {
    await api.post(`/accounts/${a.id}/loan/payments`, {
      date: c.date,
      amount: c.amount,
      transactionId: c.transactionId,
    });
    toast('Linked and split by the schedule');
    res.reload();
    again();
  });
  if (!rows.length) return null;
  return html`
    <div class="card"><h3>Looks like a payment</h3>
      ${rows.map((c) =>
        html`<div class="list-item"><div class="grow">${c.payee || 'Payment'}<div
          class="small dim">${c.accountName} · ${
          date(c.date)
        }</div></div><${Amt} v=${c.amount} /><button class="btn sm" disabled=${link.busy} onClick=${() =>
          link.run(c).catch(() => {})}>Link</button></div>`
      )}
      <p class="small dim">Linking makes it the transfer into this loan, split by the schedule.</p>
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
    return html`<${Empty}>No terms yet. Set them in Settings to compute the schedule.</${Empty}>`;
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
            html`<tr class=${r.past ? 'dim' : ''}><td style=${{
              whiteSpace: 'nowrap',
            }}>${date(r.date)}${
              r.past
                ? html`
                  <span class="pill ok">paid</span>
                `
                : null
            }</td>
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
          .length} payments. A payment that differs from the schedule, a rate reset or a recast
        recomputes the rest.</span><span class="spacer"></span><button class="btn sm"
          onClick=${() => setAll(!all)}>${all ? 'Show fewer' : 'Show all'}</button></div>
    </div>
  `;
}

const PARTS = /** @type {[string, string][]} */ ([
  ['principal', 'Principal'],
  ['interest', 'Interest'],
  ['escrowTax', 'Escrow: property tax'],
  ['escrowInsurance', 'Escrow: insurance'],
  ['pmi', 'PMI'],
  ['fees', 'Fees'],
]);

/** @param {{ close: (v?: any) => void, a: any, v: any }} p */
export function PaymentDialog({ close, a, v }) {
  useDialogGuide('dialog-loan-payment');
  const accounts = useList('/accounts');
  const banks = (/** @type {any[]} */ (accounts.data) || []).filter((x) =>
    x.group === 'banking' && x.active && ['owner', 'write'].includes(x.level)
  );
  const [f, setF] = useState({
    date: v.nextDate || today(),
    amount: v.total,
    from: '',
  });
  const [split, setSplit] = useState(/** @type {any} */ (null));
  const [typed, setTyped] = useState(false);
  const set = (/** @type {string} */ k) => (/** @type {any} */ x) => {
    setF({ ...f, [k]: x });
    if (k !== 'from') setSplit(null);
  };
  const suggest = useSubmit(async () => {
    const s = await api.post(`/accounts/${a.id}/loan/split`, {
      date: f.date,
      amount: clean(f.amount),
    });
    setSplit({ ...s, principal: String(dec(s.principal).add(dec(s.overpayment))) });
  });
  const save = useSubmit(async () => {
    /** @type {any} */
    const body = { date: f.date, amount: clean(f.amount), fromAccountId: f.from || null };
    if (typed && split) { for (const [k] of PARTS) body[k] = clean(split[k]) || '0'; }
    await api.post(`/accounts/${a.id}/loan/payments`, body, { idempotent: true });
    toast('Payment recorded and split');
    close(true);
  });
  const e = save.error || suggest.error;
  return html`
    <${Dialog} title="Record a payment" close=${close} onSubmit=${() => save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Record</button>`}>
      <div class="row">
        <${Field} label="Paid on" id="paid-on" error=${errAt(e, 'date')}>
          <${Input} type="date" value=${f.date} onInput=${set('date')} required />
          </${Field}>
          <${Field} label="Amount" id="amount" error=${errAt(e, 'amount')}>
            <${Input} value=${f.amount} onInput=${set('amount')} inputmode="decimal" required />
            </${Field}>
            </div>
            <${Field} label="From account" id="from-account" error=${errAt(e, 'fromAccountId')}
              hint="Its half of the transfer is recorded too. None: the payment is recorded here only.">
        <${Select} value=${f.from} onChange=${set('from')} options=${[
          ['', 'None'],
          ...banks.map((b) => [b.id, b.name]),
        ]} /></${Field}>
      <div class="toolbar"><span class="small dim">${split
        ? 'Split by the schedule. Correct it from the servicer’s statement if it differs.'
        : 'The schedule splits it into principal, interest, escrow and PMI.'}</span><span
        class="spacer"></span><button type="button" class="btn sm" disabled=${suggest.busy}
          onClick=${() =>
            suggest.run().then(() => setTyped(false)).catch(() => {})}>Show the split</button></div>
      ${split
        ? html`<div class="row" style=${{ flexWrap: 'wrap' }}>${
          PARTS.map(([k, label]) =>
            html`
              <${Field} label=${label} id=${'part-' + k} help="split" error=${errAt(e, k)}>
                <${Input} value=${split[k]} inputmode="decimal" onInput=${(
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
      <${FormError} error=${e} shown=${[
        'date',
        'amount',
        'fromAccountId',
        ...PARTS.map(([k]) => k),
      ]} />
    </${Dialog}>
  `;
}

/** @param {{ close: (v?: any) => void, a: any }} p */
function ServicerDialog({ close, a }) {
  useDialogGuide('dialog-servicer-balance');
  const [balance, setBalance] = useState('');
  const [day, setDay] = useState(today());
  const save = useSubmit(async () => {
    await api.post(`/accounts/${a.id}/anchors`, {
      date: day,
      balance: '-' + clean(balance).replace(/^-/, ''),
    });
    toast('Balance recorded and checked');
    close(true);
  });
  return html`
    <${Dialog} title="Type the servicer's balance" close=${close} onSubmit=${() =>
      save.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Check</button>`}>
      <p class="small dim"
        style=${{ marginTop: 0 }}>The principal still owed, from ${a
          .institution || 'the servicer'}'s statement or site. A difference from the schedule's
        balance shows until it is explained.</p>
      <div class="row">
        <${Field} label="Principal owed" id="owed" error=${errAt(save.error, 'balance')}>
          <${Input} value=${balance} onInput=${setBalance} inputmode="decimal" required />
          </${Field}>
          <${Field} label="As of" id="as-of" error=${errAt(save.error, 'date')}>
            <${Input} type="date" value=${day} onInput=${setDay} />
            </${Field}>
            </div>
            <${FormError} error=${save.error} shown=${['balance', 'date']} />
            </${Dialog}>
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
    <div class="card"><h3>Loan terms</h3>
      <${TermsFields} rec=${rec} type=${a.type} />
      <${Dated} rec=${rec} name="resets" label="Rate resets" what="rate" add="Add a reset"
        hint="An adjustable rate's new rate from a date, typed when known." />
      <${Dated} rec=${rec} name="recasts" label="Recasts" what="fee" add="Add a recast"
        hint="The servicer re-amortizes the balance over the rest of the term: a lower payment." />
      ${v?.terms
        ? html`<p class="small dim">Computed payment <${Amt} v=${v.terms.computedPayment} />.</p>`
        : null}
    </div>
  `;
}

/**
 * Dated rows of the terms: an ARM's resets (date, rate) or recasts (date, fee), a list field
 * of the loan's record.
 * @param {{ rec: LoanRec, name: string, label: string, what: string, add: string,
 *   hint: string }} p
 */
function Dated({ rec, name, label, what, add, hint }) {
  const key = what === 'rate' ? 'rate-resets' : 'recasts';
  const rows = /** @type {any[]} */ (rec.get(name) || []);
  const set = (/** @type {any[]} */ next) => rec.set(name, next);
  const put = (/** @type {number} */ i, /** @type {string} */ k, /** @type {string} */ x) =>
    set(rows.map((r, j) => (j === i ? { ...r, [k]: k === 'date' ? x : clean(x) } : r)));
  return html`
    <div class="mt"><div class="toolbar"><b class="small" data-help=${key}>${label}</b><span
      class="spacer"></span><button type="button" class="btn sm" onClick=${() =>
        set([...rows, { date: '', [what]: '0' }])}><${Icon} name="plus" /> ${add}</button></div>
      ${rows.length ? null : html`<div class="small dim">${hint}</div>`}
      ${rows.map((r, i) =>
        html`
          <div class="row">
            <${Field} label="From" help=${key} id=${`${what}-date-${i}`}>
              <${Input} type="date" value=${r.date} onInput=${(/** @type {string} */ x) =>
                put(i, 'date', x)} />
              </${Field}>
              <${Field} label=${what === 'rate' ? 'Rate' : 'Fee'} help=${key} id=${`${what}-${i}`}>
                <${Input} value=${r[what] == null ? '' : String(r[what])} inputmode="decimal"
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
