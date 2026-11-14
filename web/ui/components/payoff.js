// A loan's Payoff tab (requirements S6.10): a plan of overpayments against the schedule, worked
// out as it is typed; a recast after its lump sums; the same money invested instead; and the
// saved plans, one of them the plan being followed.
import { useEffect, useRef, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date } from '../kit/format.js';
import { Amt } from '../kit/amount.js';
import { Empty, Failed, Loading } from '../kit/bits.js';
import { errAt, Field, FormError, Input, Select, SwitchRow, TypedInput } from '../kit/fields.js';
import { check, KINDS } from '../kit/kinds.js';
import { Icon } from '../kit/icon.js';
import { toast } from '../kit/toast.js';
import { TimeChart } from '../charts/chart.js';
import { dec, num as float } from '../kit/dec.js';
import { READ_ONLY, Record } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { saveNow } from './draft-form.js';
import { Action } from '../kit/state.js';

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

/** The lump sums with a date and an amount, by their place on screen. @param {typeof BLANK} f */
const whole = (f) => f.lumps.flatMap((x, i) => (x.date && clean(x.amount) ? [i] : []));

/**
 * The plan as the API takes it. The preview leaves out a lump sum still being filled; a saved
 * plan (`all`) sends every one, so one missing its date or amount is refused at it (S6.10.1).
 * @param {typeof BLANK} f @param {boolean} [all]
 */
function body(f, all = false) {
  const rows = all ? f.lumps.map((_, i) => i) : whole(f);
  return {
    monthly: num(f.monthly),
    monthlyFrom: f.monthlyFrom || null,
    monthlyUntil: f.monthlyUntil || null,
    yearly: num(f.yearly),
    yearlyMonth: Number(f.yearlyMonth),
    lumps: rows.map((i) => ({
      date: f.lumps[i].date || null,
      amount: clean(f.lumps[i].amount) || null,
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
    return html`<${Empty} action=${html`<a class="btn sm" href=${`/ui/accounts/${a.id}/settings`}>Settings</a>`}>No terms yet</${Empty}>`;
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
  // The plan the preview shows: taken when a field is left, at Enter, or as a choice is made,
  // once every amount in it passes; what is still typed, or marked, leaves it as it was
  // (S12.18.4). `places` maps the lump sums sent to their rows on screen.
  const [taken, setTaken] = useState(() => ({
    sent: JSON.stringify(body(start)),
    places: whole(start),
  }));
  const take = (/** @type {typeof BLANK} */ next) => {
    const amounts = [next.monthly, next.yearly, next.roundTo, next.recastFee];
    const lumps = whole(next).map((i) => next.lumps[i].amount);
    if ([...amounts, ...lumps].some((v) => check(KINDS.money, { min: 0 }, v))) return;
    setTaken({ sent: JSON.stringify(body(next)), places: whole(next) });
  };
  // The plan as typed this moment: a field's change and its commit can come in one go (a
  // date's input, then its change), before the screen draws again.
  const now = useRef(f);
  now.current = f;
  /** Set what is typed; `taken` takes it too, as a choice or a row added or removed does. */
  const set = (/** @type {string} */ k, taken = false) => (/** @type {any} */ x) => {
    const next = { ...now.current, [k]: x };
    now.current = next;
    setF(next);
    if (taken) take(next);
  };
  const commit = () => take(now.current);
  // A refusal of the saved plan, at its fields; the preview's at a lump sum's row on screen.
  const [refused, setRefused] = useState(/** @type {any} */ (null));
  const lumpErr = (/** @type {number} */ i, /** @type {string} */ k) => {
    const at = taken.places.indexOf(i);
    return errAt(refused, `lumps.${i}.${k}`) || (at < 0 ? null : errAt(err, `lumps.${at}.${k}`));
  };
  const sent = taken.sent;
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
  const lump = (/** @type {number} */ i, /** @type {string} */ k) => (/** @type {string} */ x) => {
    setRefused(null);
    set('lumps')(now.current.lumps.map((l, j) => (j === i ? { ...l, [k]: x } : l)));
  };
  const className = classes.find(([k]) => k === f.investClass)?.[1] || f.investClass;
  return html`
    <div class="grid g-main">
      <div class="card"><h3>Balance: The Schedule against Your Plan</h3>
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
          <h3>Your Plan</h3>
          <${Field} label="Extra each month" error=${errAt(err, 'monthly')}>
            <${TypedInput} kind="money" min=${0} value=${f.monthly} onInput=${set('monthly')}
              onCommit=${commit} placeholder="none" />
            </${Field}>
            <div class="row">
              <${Field} label="From" id="monthly-from" error=${errAt(err, 'monthlyFrom')}>
                <${TypedInput} kind="date" value=${f.monthlyFrom} onInput=${set('monthlyFrom')}
                  onCommit=${commit} />
                </${Field}>
                <${Field} label="Until" id="monthly-until" error=${errAt(err, 'monthlyUntil')}>
                  <${TypedInput} kind="date" value=${f.monthlyUntil} onInput=${set('monthlyUntil')}
                    onCommit=${commit} />
                  </${Field}>
                  </div>
                  <div class="row">
                    <${Field} label="Extra once a year" error=${errAt(err, 'yearly')}>
                      <${TypedInput} kind="money" min=${0} value=${f.yearly} onInput=${set(
                        'yearly',
                      )}
                        onCommit=${commit} placeholder="none" />
                      </${Field}>
                      <${Field} label="In" id="yearly-month" error=${errAt(err, 'yearlyMonth')}>
              <${Select} value=${f.yearlyMonth} onChange=${set('yearlyMonth', true)}
                options=${MONTHS} /></${Field}>
          </div>
          <div class="toolbar"><b class="small" data-help="lump-sums">Lump sums</b><span
            class="spacer"></span><button type="button" class="btn sm" onClick=${() =>
              set('lumps', true)([...f.lumps, { date: '', amount: '' }])}>
              <${Icon} name="plus" /> Add a Lump Sum</button></div>
          ${f.lumps.map((l, i) =>
            html`
              <div class="row">
                <${Field} label="On" help="lump-sums" id=${'lump-date-' + i}
                  error=${lumpErr(i, 'date')}>
                  <${TypedInput} kind="date" value=${l.date} onInput=${lump(i, 'date')}
                    onCommit=${commit} />
                  </${Field}>
                  <${Field} label="Amount" help="lump-sums" id=${'lump-amount-' + i}
                    error=${lumpErr(i, 'amount')}>
                    <${TypedInput} kind="money" min=${0} value=${l.amount}
                      onInput=${lump(i, 'amount')} onCommit=${commit} />
                    </${Field}>
                    <button type="button" class="icon-btn" aria-label="Remove the lump sum"
                      onClick=${() => {
                        setRefused(null);
                        set('lumps', true)(f.lumps.filter((_, j) => j !== i));
                      }}><${Icon} name="x" /></button>
                    </div>
            `
          )}
          <${SwitchRow} label="Biweekly payments"
            hint="Half a payment every two weeks: one extra payment a year." on=${f.biweekly}
            onChange=${set('biweekly', true)} />
          <${Field} label="Round each payment up to" id="round-to" error=${errAt(err, 'roundTo')}>
            <${TypedInput} kind="money" min=${0} value=${f.roundTo} onInput=${set('roundTo')}
              onCommit=${commit} placeholder="none" />
          </${Field}>
          <${SwitchRow} label="Recast after the lump sums"
            hint="Also shows keeping the term and lowering the payment, instead of paying off sooner."
            on=${f.recast} onChange=${set('recast', true)} />
          ${f.recast
            ? html`
              <${Field} label="Recast fee" error=${errAt(err, 'recastFee')}>
                <${TypedInput} kind="money" min=${0} value=${f.recastFee}
                  onInput=${set('recastFee')} onCommit=${commit} placeholder="none" />
                </${Field}>
            `
            : null}
          <${Field} label="Invest the extra in" id="invest-class" error=${errAt(err, 'investClass')}
            hint="For the comparison: at your expected return for it (Profile › Assumptions).">
            <${Select} value=${f.investClass} onChange=${set('investClass', true)}
              options=${classes} /></${Field}>
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
          refused=${setRefused} load=${(/** @type {any} */ i) => {
            setF(form(i));
            take(form(i));
          }} />
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
  const changed = p.payoffDate !== s.payoffDate || !dec(p.interest).eq(s.interest); // exact (CR3-411)
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
                <th>After the Lump Sums</th>
                <th class="num">Payment</th>
                <th>Paid Off</th>
                <th class="num">Interest Saved</th>
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
        ? 'Hide the Plan’s Schedule'
        : 'Show the Plan’s Schedule'}</button></div>
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
 * `refused` hears the save's refusal, or null, so the plan's fields show theirs.
 * @param {{ a: any, canWrite: boolean, f: any, plans: any[], reload: () => void,
 *   load: (inputs: any) => void, refused: (e: any) => void }} p
 */
function Saved({ a, canWrite, f, plans, reload, load, refused }) {
  const [name, setName] = useState('');
  const save = useSubmit(async () => {
    refused(null);
    try {
      await saveNow((d) => d.add(PayoffRec, { accountId: a.id, name, inputs: body(f, true) }));
    } catch (e) {
      refused(e);
      throw e;
    }
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
    <div class="card"><h3>Saved Plans</h3>
      ${plans.length
        ? plans.map((p) =>
          html`
            <div
              class="list-item wraps">
              <div class="grow">${p.name}<div class="small dim">${p
                  .following
                ? html`the plan you're following, since ${date(p.followingSince)} ·${' '}`
                : null}${p.headline}</div></div>
              <button class="btn sm" onClick=${() => load(p.inputs)}>Show</button>
              <${Action} class=${'btn sm' + (p.following ? ' primary' : '')}
                why=${canWrite ? null : READ_ONLY}
                aria-pressed=${p.following ? 'true' : 'false'}
                onClick=${() => follow.run(p).catch(() => {})}>${p.following
                  ? html`<${Icon} name="check" /> Following`
                  : 'Follow'}</${Action}><${Action} class="icon-btn"
                          why=${canWrite ? null : READ_ONLY} aria-label=${'Delete ' + p.name}
                          onClick=${() =>
                            remove.run(p).catch(() => {})}><${Icon} name="x" /></${Action}></div>
          `
        )
        : html`<${Empty}>No saved plans</${Empty}>`}
      ${!canWrite
        ? html`
          <div class="toolbar mt">
            <${Action} class="btn primary" why=${READ_ONLY}>Save
                    Plan</${Action}></div>
        `
        : html`
          <form class="row mt" onSubmit=${(/** @type {Event} */ ev) => {
            ev.preventDefault();
            save.run().catch(() => {});
          }}>
            <${Field} label="Plan name" error=${errAt(save.error, 'name')}><${Input} value=${name}
                    onInput=${setName} placeholder="ex: Extra $300 a month" required /></${Field}><button
                    class="btn primary" style=${{ alignSelf: 'end' }} disabled=${save
                      .busy}>Save Plan</button></form>
        `}
    </div>
  `;
}
