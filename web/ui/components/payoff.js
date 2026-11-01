// A loan's Payoff tab (requirements S6.10): a plan of overpayments against the schedule, worked
// out as it is typed; a recast after its lump sums; the same money invested instead; and the
// saved plans, one of them the plan being followed.
import { useEffect, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date } from '../app/format.js';
import { Amt } from './amount.js';
import { Empty, Failed, Loading } from './bits.js';
import { errAt, Field, FormError, Input, Select, SwitchRow } from './fields.js';
import { Icon } from './icon.js';
import { toast } from './toast.js';
import { TimeChart } from '../charts/chart.js';
import { num as float } from '../app/dec.js';
import { Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { saveNow } from './draft-form.js';

const MONTHS = /** @type {[string, string][]} */ ([
  'January',
  'February',
  'March',
  'April',
  'May',
  'June',
  'July',
  'August',
  'September',
  'October',
  'November',
  'December',
].map((m, i) => [String(i + 1), m]));

const BLANK = {
  monthly: '',
  monthlyFrom: '',
  monthlyUntil: '',
  yearly: '',
  yearlyMonth: '12',
  lumps: /** @type {{ date: string, amount: string }[]} */ ([]),
  biweekly: false,
  roundTo: '',
  recast: false,
  recastFee: '',
  investClass: 'usStocks',
};

const clean = (/** @type {string} */ s) => (s ? String(s).replace(/[$,\s]/g, '') : '');
const num = (/** @type {string} */ s) => clean(s) || '0';

/** @param {typeof BLANK} f */
function body(f) {
  return {
    monthly: num(f.monthly),
    monthlyFrom: f.monthlyFrom || null,
    monthlyUntil: f.monthlyUntil || null,
    yearly: num(f.yearly),
    yearlyMonth: Number(f.yearlyMonth),
    lumps: f.lumps.filter((x) => x.date && clean(x.amount)).map((x) => ({
      date: x.date,
      amount: clean(x.amount),
    })),
    biweekly: f.biweekly,
    roundTo: num(f.roundTo),
    recast: f.recast,
    recastFee: num(f.recastFee),
    investClass: f.investClass,
  };
}

/** A saved plan's inputs, back in the form. */
/** @param {any} i */
function form(i) {
  const blank = (/** @type {any} */ s) => (float(s) ? String(s) : '');
  return {
    monthly: blank(i.monthly),
    monthlyFrom: i.monthlyFrom || '',
    monthlyUntil: i.monthlyUntil || '',
    yearly: blank(i.yearly),
    yearlyMonth: String(i.yearlyMonth),
    lumps: i.lumps.map((/** @type {any} */ x) => ({ date: x.date, amount: String(x.amount) })),
    biweekly: i.biweekly,
    roundTo: blank(i.roundTo),
    recast: i.recast,
    recastFee: blank(i.recastFee),
    investClass: i.investClass,
  };
}

/** A yearly rate: "6.5%". */
const rate = (/** @type {any} */ x) => `${String(x).replace(/\.0+$|(\.\d*?)0+$/, '$1')}%`;

/** "2055-01-01" as "Jan 2055". */
const month = (/** @type {string | null} */ iso) => (iso ? date(iso).replace(/ \d+,/, '') : '—');

/** @param {{ a: any }} p */
export function Payoff({ a }) {
  const loan = useApi(`/accounts/${a.id}/loan`);
  const plans = useList(`/accounts/${a.id}/loan/plans`);
  const v = /** @type {any} */ (loan.data);
  const saved = /** @type {any[] | null} */ (plans.data);
  if (loan.error || plans.error) return html`<${Failed} error=${loan.error || plans.error} />`;
  if (!v || !saved) return html`<${Loading} />`;
  if (!v.terms) {
    return html`<${Empty}>No terms yet. Set them in Settings to plan the payoff.</${Empty}>`;
  }
  // It opens on the plan being followed.
  const followed = saved.find((p) => p.following);
  return html`
    <${Planner} a=${a} canWrite=${a.access.writable} plans=${saved} reload=${plans.reload}
      start=${followed ? form(followed.inputs) : BLANK} />
  `;
}

/**
 * @param {{ a: any, canWrite: boolean, plans: any[], reload: () => void, start: typeof BLANK }} p
 */
function Planner({ a, canWrite, plans, reload, start }) {
  const [f, setF] = useState(start);
  const [res, setRes] = useState(/** @type {any} */ (null));
  const [err, setErr] = useState(/** @type {any} */ (null));
  const [rows, setRows] = useState(false);
  const figures = useApi('/assumptions');
  const classes = /** @type {[string, string][]} */ (
    /** @type {any} */ (figures.data)?.classes || [['usStocks', 'US stocks']]
  );
  const set = (/** @type {string} */ k) => (/** @type {any} */ x) => setF({ ...f, [k]: x });
  const sent = JSON.stringify(body(f));
  useEffect(() => {
    let live = true;
    const timer = setTimeout(() => {
      api.post(`/accounts/${a.id}/loan/payoff`, JSON.parse(sent)).then((r) => {
        if (!live) return;
        setRes(r);
        setErr(null);
      }).catch((e) => live && setErr(e));
    }, 300);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [sent]);
  const lump = (/** @type {number} */ i, /** @type {string} */ k) => (/** @type {string} */ x) =>
    set('lumps')(f.lumps.map((l, j) => (j === i ? { ...l, [k]: x } : l)));
  const className = classes.find(([k]) => k === f.investClass)?.[1] || f.investClass;
  return html`
    <div class="grid g-main">
      <div class="card"><h3>Balance: the schedule against your plan</h3>
        ${res
          ? html`
            <${Results} r=${res} className=${className} rows=${rows}
              showRows=${() => setRows(!rows)} />
          `
          : err
          ? html`<p class="small dim">Correct the plan to see what it does.</p>`
          : html`<${Loading} lines=${6} />`}
      </div>
      <div class="grid" style=${{ alignContent: 'start' }}>
        <div class="card">
          <h3>Your plan</h3>
          <${Field} label="Extra each month" error=${errAt(err, 'monthly')}
            hint="Added to principal with every payment.">
            <${Input} value=${f.monthly} onInput=${set('monthly')} inputmode="decimal"
              placeholder="0" />
            </${Field}>
            <div class="row">
              <${Field} label="From" id="monthly-from" error=${errAt(err, 'monthlyFrom')}>
                <${Input} type="date" value=${f.monthlyFrom} onInput=${set('monthlyFrom')} />
                </${Field}>
                <${Field} label="Until" id="monthly-until" error=${errAt(err, 'monthlyUntil')}>
                  <${Input} type="date" value=${f.monthlyUntil} onInput=${set('monthlyUntil')} />
                  </${Field}>
                  </div>
                  <div class="row">
                    <${Field} label="Extra once a year" error=${errAt(err, 'yearly')}>
                      <${Input} value=${f.yearly} onInput=${set('yearly')} inputmode="decimal"
                        placeholder="0" />
                      </${Field}>
                      <${Field} label="In" id="yearly-month" error=${errAt(err, 'yearlyMonth')}>
              <${Select} value=${f.yearlyMonth} onChange=${set('yearlyMonth')}
                options=${MONTHS} /></${Field}>
          </div>
          <div class="toolbar"><b class="small" data-help="lump-sums">Lump sums</b><span
            class="spacer"></span><button type="button" class="btn sm" onClick=${() =>
              set('lumps')([...f.lumps, { date: '', amount: '' }])}><${Icon} name="plus" /> Add a
            lump sum</button></div>
          ${f.lumps.map((l, i) =>
            html`
              <div class="row">
                <${Field} label="On" help="lump-sums" id=${'lump-date-' + i}
                  error=${errAt(err, `lumps.${i}.date`)}>
                  <${Input} type="date" value=${l.date}
                    onInput=${lump(i, 'date')} />
                  </${Field}>
                  <${Field} label="Amount" help="lump-sums"
                    id=${'lump-amount-' + i} error=${errAt(err, `lumps.${i}.amount`)}><${Input}
                              value=${l.amount} onInput=${lump(
                                i,
                                'amount',
                              )} inputmode="decimal" /></${Field}>
                            <button type="button" class="icon-btn" aria-label="Remove the lump sum" onClick=${() =>
                              set('lumps')(
                                f.lumps.filter((_, j) => j !== i),
                              )}><${Icon} name="x" /></button></div>
            `
          )}
          <${SwitchRow} label="Biweekly payments"
            hint="Half a payment every two weeks: one extra payment a year." on=${f.biweekly}
            onChange=${set('biweekly')} />
          <${Field} label="Round each payment up to" id="round-to" error=${errAt(err, 'roundTo')}
            hint="The next multiple of this, escrow included: 100 makes $2,154 into $2,200.">
            <${Input} value=${f.roundTo} onInput=${set('roundTo')} inputmode="decimal"
              placeholder="0" /></${Field}>
          <${SwitchRow} label="Recast after the lump sums"
            hint="Also shows keeping the term and lowering the payment, instead of paying off sooner."
            on=${f.recast} onChange=${set('recast')} />
          ${f.recast
            ? html`
              <${Field} label="Recast fee" error=${errAt(err, 'recastFee')}
                hint="The servicer's fee for each recast.">
                <${Input} value=${f.recastFee} onInput=${set('recastFee')} inputmode="decimal"
                  placeholder="250" />
                </${Field}>
            `
            : null}
          <${Field} label="Invest the extra in" id="invest-class" error=${errAt(err, 'investClass')}
            hint="For the comparison: at your expected return for it (Profile › Assumptions).">
            <${Select} value=${f.investClass} onChange=${set(
              'investClass',
            )} options=${classes} /></${Field}>
          <${FormError} error=${err} shown=${[
            'monthly',
            'monthlyFrom',
            'monthlyUntil',
            'yearly',
            'yearlyMonth',
            'roundTo',
            'recastFee',
            'investClass',
            ...f.lumps.flatMap((_, i) => [`lumps.${i}.date`, `lumps.${i}.amount`]),
          ]} />
        </div>
        <${Saved} a=${a} canWrite=${canWrite} f=${f} plans=${plans} reload=${reload}
          load=${(/** @type {any} */ i) => setF(form(i))} />
      </div>
    </div>
  `;
}

/**
 * @param {{ r: any, className: string, rows: boolean, showRows: () => void }} p
 */
function Results({ r, className, rows, showRows }) {
  const s = r.schedule;
  const p = r.plan;
  const rc = r.recast;
  const line = (/** @type {any} */ o) =>
    o.balances.map((/** @type {any} */ x) => /** @type {[string, string]} */ ([x.date, x.balance]));
  const changed = p.payoffDate !== s.payoffDate || p.interest !== s.interest;
  return html`
    <${TimeChart} label="The loan's balance: the schedule against your plan" series=${[
      { name: 'Schedule', color: '--fg-muted', dash: true, points: line(s) },
      { name: 'With your plan', color: '--accent', points: line(p) },
      ...(rc ? [{ name: 'Recast', color: '--hue-liability', points: line(rc) }] : []),
    ]} />
    <div class="kv mt">
      <div>
        <div class="k">Paid off</div>
        <div class="v">${month(p.payoffDate)}</div>
        <div class="small dim">scheduled ${month(s.payoffDate)}</div>
      </div>
      <div>
        <div class="k">Months saved</div>
        <div class="v">${p.monthsSaved}</div>
      </div>
      <div>
        <div class="k">Interest saved</div>
        <div class="v up">
          <${Amt} v=${p.interestSaved}
            cents=${false} />
        </div>
      </div>
      <div>
        <div class="k">Interest still to pay</div>
        <div class="v">
          <${Amt} v=${p.interest}
            cents=${false} />
        </div>
      </div>
      <div>
        <div class="k">Total paid</div>
        <div class="v">
          <${Amt} v=${p.paid}
            cents=${false} />
        </div>
      </div>
    </div>
    ${rc
      ? html`
        <div class="table-wrap mt">
          <table class="t">
            <caption class="sr-only">Shortening the loan against recasting it</caption>
            <thead>
              <tr>
                <th>After the lump sums</th>
                <th class="num">Payment</th>
                <th>Paid off</th>
                <th class="num">Interest saved</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>Shorten the loan</td>
                <td class="num">
                  <${Amt} v=${p.paymentAfter} />
                </td>
                <td>${month(p.payoffDate)}</td>
                <td class="num">
                  <${Amt} v=${p.interestSaved}
                    cents=${false} />
                </td>
              </tr>
              <tr>
                <td>Recast${float(rc.fees)
                  ? html`<span class="small dim"> · <${Amt} v=${rc.fees} /> in fees</span>`
                  : null}</td>
                <td class="num">
                  <${Amt} v=${rc.paymentAfter} />
                </td>
                <td>${month(rc.payoffDate)}</td>
                <td class="num">
                  <${Amt} v=${rc.interestSaved}
                    cents=${false} />
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      `
      : null}
    ${changed
      ? html`
        <div class="notice mt">
          <${Icon} name="info" />
          <div>${[
            'Investing the same ',
            html`<${Amt} v=${r.invested.contributed} cents=${false} />`,
            ` in ${className} at ${rate(r.invested.rate)} a year instead would be worth about `,
            html`<b><${Amt} v=${r.invested.value} cents=${false} /></b>`,
            ` by ${month(p.payoffDate)}, against `,
            html`<b><${Amt} v=${p.interestSaved} cents=${false} /></b>`,
            ' of interest saved. A comparison, not advice: the return is an assumption; the',
            ' interest saved is certain.',
          ]}</div>
        </div>
      `
      : html`<p class="small dim mt">Add an overpayment to see what it saves.</p>`}
    ${r.assumedRates.length
      ? html`
        <div class="notice warn mt">
          <${Icon} name="alert" />
          <div>After ${date(
            r.assumedRates[0].date,
          )} the rate is your assumption (${r.assumedRates.map((/** @type {any} */ x) =>
            `${rate(x.rate)} from ${month(x.date)}`
          ).join(', ')}), as typed in the terms.</div>
        </div>
      `
      : null}
    <div class="toolbar mt"><span class="spacer"></span><button type="button" class="btn sm"
      onClick=${showRows}>${rows
        ? 'Hide the plan’s schedule'
        : 'Show the plan’s schedule'}</button></div>
    ${rows ? html`<${PlanRows} rows=${r.planRows} />` : null}
  `;
}

/** @param {{ rows: any[] }} p */
function PlanRows({ rows }) {
  return html`
    <div class="table-wrap">
      <table class="t">
        <caption class="sr-only">The schedule with your plan</caption>
        <thead>
          <tr>
            <th>Due</th>
            <th class="num">Principal</th>
            <th class="num">Interest</th>
            <th class="num">Extra</th>
            <th class="num">Balance</th>
          </tr>
        </thead>
        <tbody>${rows.map((x) =>
          html`
            <tr>
              <td>${date(x.date)}</td>
              <td class="num">
                <${Amt} v=${x.principal} />
              </td>
              <td class="num">
                <${Amt} v=${x.interest} />
              </td>
              <td class="num">${float(x.overpayment)
                ? html`<${Amt} v=${x.overpayment} />`
                : html`<span class="dim">—</span>`}</td>
              <td class="num">
                <${Amt} v=${x
                  .balance} />
              </td>
            </tr>
          `
        )}</tbody>
      </table>
    </div>
  `;
}

/** A saved overpayment plan (S1.9.6): its name and the planner's inputs. */
class PayoffRec extends Record {
  /** @override */
  static prefix = 'Pyoff';
  /** @override */
  static fields = FIELDS.PayoffRecord;
}

/**
 * @param {{ a: any, canWrite: boolean, f: any, plans: any[], reload: () => void,
 *   load: (inputs: any) => void }} p
 */
function Saved({ a, canWrite, f, plans, reload, load }) {
  const [name, setName] = useState('');
  const save = useSubmit(async () => {
    await saveNow((d) => d.add(PayoffRec, { accountId: a.id, name, inputs: body(f) }));
    toast('Plan saved');
    setName('');
    reload();
  });
  const follow = useSubmit(async (/** @type {any} */ p) => {
    await api.post(`/accounts/${a.id}/loan/plans/${p.id}/follow`, {
      following: !p.following,
    });
    toast(p.following ? 'No longer following it' : 'Following it from today');
    reload();
  });
  const remove = useSubmit(async (/** @type {any} */ p) => {
    await saveNow((d) => d.remove(d.load(PayoffRec, { ...p, accountId: a.id })));
    toast(`${p.name} deleted`);
    reload();
  });
  return html`
    <div class="card"><h3>Saved plans</h3>
      ${plans.length
        ? plans.map((p) =>
          html`
            <div
              class="list-item"><div class="grow">${p.name}<div class="small dim">${p
                  .following
                ? html`
                  the plan you're following, since ${date(p.followingSince)} ·
                `
                : null}${p.headline}</div></div>
                        <button class="btn sm" onClick=${() => load(p.inputs)}>Show</button>
                        ${canWrite
                          ? html`
                            <button class=${'btn sm' + (p.following ? ' primary' : '')}
                              aria-pressed=${p.following ? 'true' : 'false'} onClick=${() =>
                                follow.run(p).catch(() => {})}>${p.following
                                ? html`<${Icon} name="check" /> Following`
                                : 'Follow'}</button><button class="icon-btn"
                              aria-label=${'Delete ' + p.name}
                              onClick=${() =>
                                remove.run(p).catch(() => {})}><${Icon} name="x" /></button>
                          `
                          : null}</div>
          `
        )
        : html`<p class="small dim" style=${{ marginTop: 0 }}>None yet. Save a plan to compare it
          later, and follow one to see whether you're ahead of it.</p>`}
      ${canWrite
        ? html`
          <form class="row mt" onSubmit=${(/** @type {Event} */ ev) => {
            ev.preventDefault();
            save.run().catch(() => {});
          }}>
            <${Field} label="Plan name" error=${errAt(save.error, 'name')}><${Input} value=${name}
                    onInput=${setName} placeholder="Extra $300 a month" required /></${Field}><button
                    class="btn primary" style=${{ alignSelf: 'end' }} disabled=${save
                      .busy}>Save plan</button></form>
        `
        : null}
    </div>
  `;
}
