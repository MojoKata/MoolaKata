// Projections (requirements S6): the active plans being followed and the scenarios, one at a
// time below them with its fan or paths, its answer, the assumptions in full, and its inputs.
// A model, not a forecast.
import { useRef, useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date, money, thisYear } from '../kit/format.js';
import { useTitle } from '../components/frame.js';
import { useDialogGuide, useGuide } from '../components/help.js';
import { Chips, Empty, Failed, Loading } from '../kit/bits.js';
import { Icon } from '../kit/icon.js';
import { Dialog, openDialog } from '../kit/dialog.js';
import {
  errAt,
  Field,
  FormError,
  Input,
  Seg,
  Select,
  SpinInput,
  TypedInput,
} from '../kit/fields.js';
import { toast } from '../kit/toast.js';
import { ShareDialog } from '../components/share.js';
import { FanChart, TimeChart } from '../charts/chart.js';
import { num } from '../kit/dec.js';
import { Record as Rec, whyNot } from '../app/draft.js';
import { DraftForm, saveNow, saveOne, useDraft } from '../components/draft-form.js';
import { FIELDS } from '../api/fields.js';
import { Action, StatePill } from '../kit/state.js';

const GOAL = /** @type {Record<string, [string, string]>} */ ({
  retirement: ['Retirement', 'retire'],
  savings: ['Savings target', 'target'],
  education: ['Education', 'grad'],
});
const TILE = /** @type {Record<string, string>} */ ({
  retirement: 'retirement',
  savings: 'banking',
  education: 'education',
});
export const COST_BASIS = /** @type {[string, string][]} */ ([
  ['public', 'Public four-year, in-state (shipped average)'],
  ['private', 'Private nonprofit four-year (shipped average)'],
  ['typed', 'Typed'],
]);
const TONE = /** @type {Record<string, string>} */ ({
  'on track': 'ok',
  ahead: 'ok',
  behind: 'warn',
});

/** @param {number} x */
const pct = (x) => `${Math.round(num(x) * 100)}%`;
/** @param {number} v */
const dollars = (v) => money(String(Math.round(num(v))), { cents: false });

/** @param {{ id?: string }} p */
export default function Projections({ id }) {
  useTitle('Projections');
  useGuide('projections');
  const list = useList('/projections', {}, ['share']);
  const rows = /** @type {any[]} */ (list.data);
  if (list.error) return html`<${Failed} error=${list.error} />`;
  if (!rows) return html`<${Loading} lines=${6} />`;
  const create = () =>
    openDialog(NewProjection, {}).then((p) => {
      if (p) {
        list.reload();
        location.assign(`/ui/projections/${p.id}`);
      }
    });
  const current = rows.find((r) => r.id === id) || rows.find((r) => r.active) || rows[0];
  const active = rows.filter((r) => r.active);
  const scenarios = rows.filter((r) => !r.active);
  const item = (/** @type {any} */ r) =>
    html`
      <a class=${'list-item' + (current && r.id === current.id ? ' sel' : '')}
        href=${`/ui/projections/${r.id}`} style=${{ color: 'inherit' }}>
            <div class=${'tile t-' + (TILE[r.goal] || 'banking')}><${Icon}
              name=${GOAL[r.goal]?.[1] || 'target'} /></div>
            <div class="grow"><span class="row-name">${r.name}</span> ${r.status
              ? html`<span class=${'pill ' + (TONE[r.status] || '')}>${r.status}</span>`
              : null}
              <div class="row-more">${r.headline} · on ${r.builtOnLabel}${r.access.mine
                ? ''
                : ` · shared by ${r.ownerName}`}</div></div></a>
    `;
  return html`
    <div class="grid g2">
      <div class="card"><h3>Active</h3>
        ${active.length ? active.map(item) : html`<${Empty}>None yet</${Empty}>`}</div>
      <div class="card"><h3>Scenarios<span class="spacer"></span><button type="button"
        class="btn sm" onClick=${create}><${Icon} name="plus" /> New Projection</button></h3>
        ${scenarios.length ? scenarios.map(item) : html`<${Empty}>None</${Empty}>`}</div>
    </div>
    ${current
      ? html`<${Detail} key=${current.id} id=${current.id} reloadList=${list.reload} />`
      : html`<${Empty} action=${html`<button type="button" class="btn primary" onClick=${create}>
          <${Icon} name="plus" /> New Projection</button>`}>No projections yet</${Empty}>`}
  `;
}

/** @param {{ id: string, reloadList: () => void }} p */
function Detail({ id, reloadList }) {
  const res = useApi(`/projections/${id}`, {}, ['share']);
  const x = /** @type {any} */ (res.data);
  const [real, setReal] = useState('nominal');
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!x) return html`<${Loading} lines=${8} />`;
  const r = x.result;
  const a = r.answer;
  const mine = x.access.mine;
  const reload = () => {
    res.reload();
    reloadList();
  };
  const activate = () =>
    openDialog(MakeActive, { p: x }).then((done) => {
      if (done) {
        toast(`${x.name} is the active plan`);
        reload();
      }
    });
  const p = real === 'real' ? r.real : r.percentiles;
  const marks =
    /** @type {[number, string][]} */ (a.kind === 'retirement'
      ? [[a.retireYear, 'retires']]
      : a.kind === 'education'
      ? [[a.firstYear, 'school starts']]
      : []);
  const classes = Object.entries(r.weights).map(([k, w]) =>
    `${r.assumptions.classes[k] ? labelOf(k) : k} ${Math.round(num(w) * 100)}%`
  ).join(', ');
  return html`
    <div class="toolbar mt">
      <b style=${{ fontSize: '16px' }}>${x.name}</b> <span class="small dim">${GOAL[x.goal]?.[0] ||
        x.goal} · on ${x.builtOnLabel}</span> ${x.active
        ? html`<span class=${'pill ' + (TONE[x.status] || '')}>active${
          x.status && x.status !==
              'untracked'
            ? ` · ${x.status}`
            : ''
        }</span>`
        : html`<span class="pill">scenario</span>`}<span class="spacer"></span><${Action} why=${whyNot(
          x,
          'shareable',
        )}
        onClick=${() =>
          openDialog(ShareDialog, { kind: 'projection', id: x.id, name: x.name }).then(
            reload,
          )}><${Icon} name="share" /> Share</${Action}>
      ${!mine
        ? html`<label class="small dim" style=${{
          display: 'flex',
          gap: '6px',
          alignItems: 'center',
        }}>
          <input type="checkbox" id="f-show-on-dashboard" checked=${x.shown} onChange=${() =>
          showOnDashboard(x).then(reload, (e) => toast(e.message))} /> Show on my
          Dashboard</label>`
        : null}
      ${!x.active
        ? html`
          <${Action} class="btn primary" why=${whyNot(x, 'configurable')}
            onClick=${activate}>Make Active</${Action}>
        `
        : html`<${Action} why=${whyNot(x, 'configurable')} onClick=${() =>
          api.post(`/projections/${x.id}/deactivate`).then(() => {
            toast('It is a scenario again');
            reload();
          })}>Stop Following</${Action}>`}
    </div>
    ${x.tracking && x.tracking.status !== 'untracked'
      ? html`<${Tracking} x=${x} />`
      : x.active
      ? html`
        <div class="mt">
          <${StatePill}
            why="Built on a typed amount: there is no balance to track it against."
          >untracked</${StatePill}></div>
      `
      : null}
    <div class="grid g-main mt">
      <div class="card">
        <h3>Projected Value · ${r.scenarios && Object.keys(r.scenarios).length
          ? 'Bear, Base and Bull'
          : `Monte Carlo, ${r.runs.toLocaleString()} runs`}<span class="spacer"></span>
        <${Chips} label="Dollars" value=${real} onChange=${setReal}
          options=${[['nominal', 'Nominal'], ['real', "Today's dollars"]]} /></h3>
        <${FanChart} label=${`${x.name}: projected value by year`} years=${r.years} p=${p}
          paths=${real === 'nominal' ? r.scenarios : null} marks=${marks} />
        <div class="small dim" data-help="projected-value">
          <div>Starts from: ${dollars(r.start)} (${classes})</div>
          <div>Returns (${mine ? 'your' : `${x.ownerName}'s`} assumptions): ${Object.entries(
            r.weights,
          ).map(([k]) =>
            `${labelOf(k)} ${r.assumptions.classes[k].return}% ± ${
              r.assumptions.classes[k].volatility
            }%`
          ).join(', ')}</div>
          <div>Inflation: ${r.assumptions.inflation}% · Fees: ${x.inputs.fees ?? 0.1}% a year</div>
          ${r.bitcoinModel !== 'assumption' && num(r.bitcoinShare ?? 0) > 0
            ? html`<div>Bitcoin: the ${r.bitcoinModel} model</div>`
            : null}
          <div>Seed: ${r.seed}</div>
        </div>
        ${r.leftOut?.length
          ? html`<p class="small dim" data-help="left-out">Left out: ${
            r.leftOut.map((
              /** @type {any} */ o,
            ) => `${o.name} ${dollars(o.value)}`).join('; ')
          }</p>`
          : null}
      </div>
      <div class="grid" style=${{ alignContent: 'start' }}>
        ${a.kind === 'retirement'
          ? html`
            <div class="card kpi">
              <div class="label">Chance the Money Lasts to ${a
                .horizonAge}</div>
              <div class=${'value ' + (num(a.chance) >= 0.9 ? 'up' : '')}>${pct(a.chance)}</div>
              <div class="delta dim">median at retirement (${a.retireYear}) ${dollars(
                a.atRetirement,
              )}</div>
            </div>
          `
          : a.kind === 'education'
          ? html`<${EducationAnswer} a=${a} />`
          : html`
            <div class="card kpi">
              <div class="label">Chance of ${dollars(a.target)} by ${date(a.date)}</div>
              <div class=${'value ' + (num(a.chance) >= 0.9 ? 'up' : '')}>${pct(a.chance)}</div>
              <div
                class="delta dim">saving ${dollars(a.monthly)} a month; ${a.neededMonthly === null
                  ? 'no monthly saving reaches it by then'
                  : html`${
                    dollars(a.neededMonthly)
                  } a month would reach it with a 90% chance`}</div>
            </div>
          `}
        <${Inputs} x=${x} reload=${reload} />
      </div>
    </div>
  `;
}

/** The education goal's answer (S6.2.2): the balance when school starts against what its
 * years will cost. */
/** @param {{ a: any }} p */
export function EducationAnswer({ a }) {
  const funded = Math.round(num(a.funded));
  return html`
    <div class="card kpi">
      <div class="label">Funded for ${a.name}'s ${a.years} Years of School</div>
      <div class=${'value ' + (funded >= 100 ? 'up' : '')}>${funded}%</div>
      <div
        class="delta dim">median ${dollars(a.atStart)} when school starts in ${a
          .firstYear}, against ${dollars(a.needed)} needed then${a.neededMonthly === null
          ? '; no monthly saving reaches it by then'
          : a.neededMonthly
          ? html`; ${dollars(a.neededMonthly)} a month would fund it fully`
          : ''}</div>
    </div>
  `;
}

/** @param {string} k */
function labelOf(k) {
  return /** @type {Record<string, string>} */ ({
    usStocks: 'US stocks',
    intlStocks: 'international stocks',
    bonds: 'bonds',
    cash: 'cash',
    crypto: 'crypto',
    realEstate: 'real estate',
    metals: 'metals',
  })[k] || k;
}

/** The actual balance against the baseline it was made active with. @param {{ x: any }} p */
function Tracking({ x }) {
  const t = x.tracking;
  const at = (/** @type {number} */ k) =>
    t.band.map((/** @type {any[]} */ b) => [b[0], String(b[k])]);
  return html`
    <div class="card mt"><h3>Tracking since ${date(t.since)}<span class="spacer"></span><span
      class=${'pill ' + (TONE[t.status] || '')}>${t.status}</span>${t.partial
        ? html`
          ${' '}<${StatePill}
            why="Some of the accounts it is built on aren't shared with you: the status is the whole projection's, the balance only that of the accounts you can see."
          >partly shared</${StatePill}>
        `
        : null}</h3>
      ${t.points.length > 1
        ? html`<${TimeChart} label=${
          t.partial
            ? 'Actual balance of the accounts shared with you'
            : 'Actual balance against the baseline'
        } series=${[
          { name: 'Actual', color: '--accent', points: t.points.map(([d, v]) => [d, String(v)]) },
          ...(t.partial ? [] : [
            { name: 'Baseline median', color: '--fg-muted', dash: true, points: at(2) },
            { name: '10th percentile', color: '--border-strong', dash: true, points: at(1) },
            { name: '90th percentile', color: '--border-strong', dash: true, points: at(3) },
          ]),
        ]} />`
        : html`<${Empty}>Nothing to chart yet</${Empty}>`}
    </div>
  `;
}

/** The person's own record, as Show on my Dashboard changes its shown projections. */
class ShownRec extends Rec {
  /** @override */
  static prefix = 'User';
  /** @override */
  static fields = FIELDS.UserRecord;
}

/**
 * A shared active projection shown on the receiver's Dashboard, or no longer (S6.8.3): a set
 * of their own record's.
 * @param {any} x
 */
async function showOnDashboard(x) {
  const me = await api.get('/profile');
  const ids = /** @type {string[]} */ (me.shownProjectionIds);
  await saveOne(ShownRec, { id: me.id, version: me.version, shownProjectionIds: ids }, {
    shownProjectionIds: x.shown ? ids.filter((i) => i !== x.id) : [...ids, x.id],
  });
}

/** A projection (S6.6), as its drafts make it and change its inputs. */
class ProjRec extends Rec {
  /** @override */
  static prefix = 'Prjct';
  /** @override */
  static fields = FIELDS.ProjectionRecord;
  /** @override */
  static defaults = { rebaseline: false };
}

/**
 * The inputs, saved with Run. An active projection asks whether its baseline should move to
 * the new inputs (S6.7.4). One who can only read sees them read, Run off (S12.18.6).
 * @param {{ x: any, reload: () => void }} p
 */
function Inputs({ x, reload }) {
  const fd = useDraft((draft) => {
    draft.load(ProjRec, { ...x, rebaseline: false });
  }, [x.id, x.version]);
  const rec = /** @type {ProjRec | undefined} */ (fd.draft?.records[0]);
  const f = rec?.get('inputs') || {};
  const built = rec?.get('builtOn') || { kind: 'typed', amount: 100000 };
  const setF = (/** @type {any} */ v) => rec?.set('inputs', v);
  const setBuilt = (/** @type {any} */ v) => rec?.set('builtOn', v);
  // The refusals at their inputs, as errAt reads them.
  const e = { errors: rec?.errors || [] };
  // An active projection asks first whether its baseline moves to the new inputs (S6.7.4).
  const asked = useRef(false);
  const runRef = useRef(/** @type {any} */ (null));
  const before = () => {
    if (!x.active || asked.current || !fd.draft?.changed) {
      asked.current = false;
      return;
    }
    openDialog(Rebaseline, { name: x.name }).then((answer) => {
      if (answer === undefined || !rec) return;
      rec.set('rebaseline', answer);
      asked.current = true;
      runRef.current?.run().catch(() => {});
    });
    return false;
  };
  const set = (/** @type {string} */ path, num = true) => (/** @type {string} */ v) => {
    const next = structuredClone(f);
    const keys = path.split('.');
    let o = next;
    for (const k of keys.slice(0, -1)) o = o[k] ??= {};
    o[keys[keys.length - 1]] = num ? (v === '' ? null : Number(v)) : v;
    setF(next);
  };
  const people = f.people || [];
  return html`
    <${DraftForm} f=${fd} class="card" where="the projection's inputs" what="This projection"
      label="Run" before=${before} read=${!x.access.writable} saved=${() => {
        toast('Recomputed');
        reload();
      }}
      extra=${({ save }) => {
        runRef.current = save;
        return null;
      }}><h3>Inputs</h3>
      <${BuiltOn} value=${built} onChange=${setBuilt} error=${errAt(e, 'builtOn')} />
      ${x.goal === 'retirement'
        ? html`
          ${people.map((/** @type {any} */ p, /** @type {number} */ i) =>
            html`
              <div class="row">
                <${Field} label=${i ? 'Partner retirement age' : 'Retirement age'}
                  id=${i ? 'partner-retirement-age' : 'retirement-age'}
                  hint=${`${p.name || 'Born'} ${p.birthYear}`}
                  error=${errAt(e, `inputs.people.${i}.retireAge`)}>
                  <${SpinInput} min=${30} max=${90} value=${p.retireAge} onInput=${(
                    /** @type {string} */ v,
                  ) => {
                    const next = structuredClone(f);
                    next.people[i].retireAge = Number(v);
                    setF(next);
                  }} />
                  </${Field}>
                  </div>
            `
          )}
          <div class="row">
            <${Field} label="Contribution per year" id="contribution"
              error=${errAt(e, 'inputs.contribution.amount')}>
              <${TypedInput} kind="money" value=${f.contribution?.amount ?? ''}
                onInput=${set('contribution.amount')} />
              </${Field}>
              <${Field} label="Grows yearly by (%)" id="contribution-growth"
                error=${errAt(e, 'inputs.contribution.growth')}>
                <${TypedInput} kind="quantity" value=${f.contribution?.growth ?? ''}
                  onInput=${set('contribution.growth')} />
                </${Field}>
                </div>
                <${Field} label="Withdrawal" id="withdrawal" error=${errAt(
                  e,
                  'inputs.withdrawal.method',
                )}>
            <${Select} value=${f.withdrawal?.method || 'fourPercent'}
              onChange=${set('withdrawal.method', false)} options=${[
                ['fourPercent', 'The 4% rule: 4% at retirement, then rising with inflation'],
                ['fixed', 'A fixed amount a year, rising with inflation'],
                ['percent', 'A percentage of the balance each year'],
              ]} />
          </${Field}>
          ${f.withdrawal?.method === 'fixed'
            ? html`
              <${Field} label="Withdrawal a year, in today's dollars" id="withdrawal-amount">
                <${TypedInput} kind="money" value=${f.withdrawal?.amount ?? ''}
                  onInput=${set('withdrawal.amount')} />
                </${Field}>
            `
            : f.withdrawal?.method === 'percent'
            ? html`
              <${Field} label="Percentage of the balance" id="withdrawal-percent">
                <${TypedInput} kind="quantity" value=${f.withdrawal?.percent ?? 4}
                  onInput=${set('withdrawal.percent')} />
                </${Field}>
            `
            : null}
          ${(f.income || []).map((/** @type {any} */ inc, /** @type {number} */ i) =>
            html`
              <div class="row">
                <${Field} label=${`${inc.label || 'Other income'} a month`} id=${'income-' + i}
                  help="other-income"
                  hint=${`From age ${inc.fromAge}`}>
                  <${TypedInput} kind="money" value=${inc.monthly} onInput=${(
                    /** @type {string} */ v,
                  ) => {
                    const next = structuredClone(f);
                    next.income[i].monthly = Number(v);
                    setF(next);
                  }} />
                  </${Field}>
                  </div>
            `
          )}
        `
        : x.goal === 'education'
        ? html`<${EducationInputs} f=${f} set=${set} setF=${setF} e=${e} />`
        : html`
          <div class="row">
            <${Field} label="Target amount" id="target" error=${errAt(e, 'inputs.target')}>
              <${TypedInput} kind="money" value=${f.target ?? ''} onInput=${set('target')} />
              </${Field}>
              <${Field} label="Target date" id="target-date" error=${errAt(e, 'inputs.date')}>
                <${TypedInput} kind="date" value=${f.date || ''} onInput=${set('date', false)} />
                </${Field}>
                </div>
                <${Field} label="Saving per month" id="monthly" error=${errAt(e, 'inputs.monthly')}>
                  <${TypedInput} kind="money" value=${f.monthly ?? ''} onInput=${set(
                    'monthly',
                  )} />
                  </${Field}>
        `}
      <div class="row">
        <${Field} label="Fees a year (%)" id="fees" error=${errAt(e, 'inputs.fees')}>
          <${TypedInput} kind="quantity" value=${f.fees ?? 0.1} onInput=${set('fees')} />
        </${Field}>
        <${Field} label="Bitcoin model" id="bitcoin-model">
          <${Select} value=${f.bitcoinModel || ''} onChange=${set('bitcoinModel', false)}
            options=${[
              ['', 'From my assumptions'],
              ['assumption', 'The crypto assumption'],
              ['powerLaw', 'Power law'],
              ['logRegression', 'Log regression'],
              ['stockToFlow', 'Stock-to-flow'],
              ['saylor', 'Saylor, Bitcoin24'],
              ['ark', 'ARK Invest 2030'],
            ]} />
        </${Field}>
      </div>
    </${DraftForm}>
  `;
}

/**
 * An education goal's inputs: who it is for, when school starts and for how long, what a year
 * costs, and the saving each month.
 * @param {{ f: any, set: (path: string, num?: boolean) => (v: string) => void,
 *   setF: (f: any) => void, e: any }} p
 */
function EducationInputs({ f, set, setF, e }) {
  const people = useList('/persons');
  const list = /** @type {any[]} */ (people.data) || [];
  const who = f.beneficiary ? `${f.beneficiary.kind}:${f.beneficiary.id}` : '';
  return html`
    <${Field} label="For" id="beneficiary" error=${errAt(e, 'inputs.beneficiary')}>
      <${Select} value=${who} onChange=${(/** @type {string} */ v) => {
        const [kind, id] = v.split(':');
        setF({ ...f, beneficiary: { kind, id } });
      }} options=${[
        ...(who && !list.some((p) => `person:${p.id}` === who) ? [[who, 'As chosen']] : []),
        ...list.map((p) => [`person:${p.id}`, p.name]),
      ]} />
      </${Field}>
      <div class="row">
        <${Field} label="Age school starts" id="start-age" error=${errAt(e, 'inputs.startAge')}>
          <${SpinInput} min=${3} max=${40} value=${f.startAge ?? 18} onInput=${set('startAge')} />
          </${Field}>
          <${Field} label="Years of school" id="school-years" error=${errAt(
            e,
            'inputs.schoolYears',
          )}>
            <${SpinInput} min=${1} max=${12} value=${f.schoolYears ?? 4} onInput=${set(
              'schoolYears',
            )} />
            </${Field}>
            </div>
            <${Field} label="Cost per year" id="cost-basis" error=${errAt(e, 'inputs.costBasis')}>
      <${Select} value=${f.costBasis || 'public'} onChange=${set('costBasis', false)}
        options=${COST_BASIS} />
    </${Field}>
    ${f.costBasis === 'typed'
      ? html`
        <${Field} label="Cost per year, typed" id="cost" error=${errAt(e, 'inputs.cost')}>
          <${TypedInput} kind="money" value=${f.cost ?? ''} onInput=${set('cost')} />
          </${Field}>
      `
      : null}
    <${Field} label="Saving per month" id="monthly" error=${errAt(e, 'inputs.monthly')}>
      <${TypedInput} kind="money" value=${f.monthly ?? ''} onInput=${set('monthly')} />
    </${Field}>
  `;
}

/**
 * What a projection is built on: a portfolio, chosen accounts, or a typed amount.
 * @param {{ value: any, onChange: (v: any) => void, error?: string | null }} p
 */
function BuiltOn({ value, onChange, error }) {
  const ports = useList('/portfolios');
  const accts = useList('/accounts');
  const options = /** @type {[string, string][]} */ ([
    ...(/** @type {any[]} */ (ports.data) || []).filter((p) => !p.implicit).map((p) => [
      `portfolio:${p.id}`,
      `Portfolio: ${p.name}`,
    ]),
    ...(/** @type {any[]} */ (accts.data) || []).map((a) => [`accounts:${a.id}`, a.name]),
    ['typed', 'A typed amount (what if)'],
  ]);
  const current = value.kind === 'portfolio'
    ? `portfolio:${value.id}`
    : value.kind === 'accounts'
    ? `accounts:${value.ids?.[0]}`
    : 'typed';
  return html`
    <${Field} label="Built on" id="built-on" error=${error}
      hint=${value.kind === 'accounts' && value.ids?.length > 1
        ? `${value.ids.length} accounts`
        : undefined}>
      <${Select} value=${current} options=${options} onChange=${(/** @type {string} */ v) => {
        if (v === 'typed') onChange({ kind: 'typed', amount: 100000 });
        else {
          const [kind, id] = v.split(':');
          onChange(kind === 'portfolio' ? { kind, id } : { kind, ids: [id] });
        }
      }} />
    </${Field}>
    ${value.kind === 'typed'
      ? html`
        <${Field} label="Amount" id="typed-amount">
          <${TypedInput} kind="money" value=${value.amount} onInput=${(/** @type {string} */ v) =>
            onChange({ ...value, amount: Number(v) })} />
          </${Field}>
      `
      : null}
  `;
}

/** @param {{ close: (v?: any) => void, name: string }} p */
function Rebaseline({ close, name }) {
  useDialogGuide('dialog-rebaseline');
  return html`
    <${Dialog} title="Re-baseline?" close=${() => close(undefined)}
      footer=${html`
        <button type="button" class="btn" onClick=${() =>
          close(false)}>Keep the Baseline</button><button
          type="button" class="btn primary"
          onClick=${() => close(true)}>Re-baseline</button>
      `}>
      <p style=${{ marginTop: 0 }}>${name} is active.</p>
      </${Dialog}>
  `;
}

/** @param {{ close: (v?: any) => void, p: any }} props */
function MakeActive({ close, p }) {
  useDialogGuide('dialog-make-active');
  const list = useList('/projections');
  const go = useSubmit(async () => {
    await api.post(`/projections/${p.id}/activate`);
    close(true);
  });
  const others = (/** @type {any[]} */ (list.data) || []).filter((r) =>
    r.active && r.goal === p.goal && r.id !== p.id && r.access.mine
  );
  return html`
    <${Dialog} title=${`Make “${p.name}” Active?`} close=${close}
      onSubmit=${() => go.run().catch(() => {})}
      footer=${html`<button class="btn primary" disabled=${go.busy}>Make Active</button>`}>
      <p style=${{ marginTop: 0 }}>${others.length && p.goal === 'retirement'
        ? html`<b>${others[0].name}</b> stops being the active plan for the same people, if
          they are the same. Its tracking ends, and it stays as a scenario.`
        : 'It becomes an active plan.'}</p>
      <${FormError} error=${go.error} />
      </${Dialog}>
  `;
}

/** @param {{ close: (v?: any) => void }} props */
function NewProjection({ close }) {
  useDialogGuide('dialog-new-projection');
  const me = useApi('/profile');
  const [goal, setGoal] = useState('retirement');
  const [name, setName] = useState('');
  const [built, setBuilt] = useState(/** @type {any} */ ({ kind: 'typed', amount: 100000 }));
  const [who, setWho] = useState('me');
  const people = useList('/persons');
  const [child, setChild] = useState('');
  const save = useSubmit(async () => {
    const p = /** @type {any} */ (me.data);
    const born = p?.birthYear || thisYear() - 40;
    const people = [{ name: p?.displayName || 'Me', birthYear: born, retireAge: 65 }];
    if (who === 'couple' && p?.spouse) {
      people.push({
        name: p.spouse.displayName,
        birthYear: p.spouse.birthYear || born,
        retireAge: 65,
      });
    }
    const year = thisYear();
    const inputs = goal === 'retirement'
      ? {
        people,
        contribution: { amount: 20000, growth: 3 },
        withdrawal: { method: 'fourPercent' },
        income: [{ label: 'Social Security', person: 0, fromAge: 67, monthly: 2500 }],
        fees: 0.1,
      }
      : goal === 'education'
      ? {
        beneficiary: child ? { kind: 'person', id: child } : null,
        startAge: 18,
        schoolYears: 4,
        costBasis: 'public',
        monthly: 200,
        fees: 0.1,
      }
      : { target: 50000, date: `${year + 3}-06-01`, monthly: 500, fees: 0.1 };
    const out = await saveNow((d) => {
      d.add(ProjRec, { name, goal, builtOn: built, inputs });
    });
    close(out[0].record);
  });
  return html`
    <${Dialog} title="New Projection" close=${close} onSubmit=${() => save.run().catch(() => {})}
      changed=${() => !!name || goal !== 'retirement' || built.kind !== 'typed' || !!child}
      footer=${html`<button class="btn primary" disabled=${save.busy}>Create</button>`}>
      <div class="field" data-help="goal" id="x-goal"><label>Goal type</label>
        <${Seg} label="Goal type" value=${goal} onChange=${setGoal}
          options=${[['retirement', 'Retirement'], ['savings', 'Savings target'], [
            'education',
            'Education',
          ]]} /></div>
      <${Field} label="Name" error=${errAt(save.error, 'name')}>
        <${Input} value=${name} onInput=${setName} required />
      </${Field}>
      <${BuiltOn} value=${built} onChange=${setBuilt} error=${errAt(save.error, 'builtOn')} />
      ${goal === 'education'
        ? html`
          <${Field} label="For" id="beneficiary" error=${errAt(
            save.error,
            'inputs.beneficiary',
          )}>
            <${Select} value=${child} onChange=${setChild} options=${[
              ['', 'Choose…'],
              ...(/** @type {any[]} */ (people.data) || []).map((p) => [p.id, p.name]),
            ]} />
            </${Field}>
        `
        : null}
      ${goal === 'retirement'
        ? html`
          <${Field} label="Who" id="who">
            <${Select} value=${who} onChange=${setWho} options=${[['me', 'Me'], [
              'couple',
              'Me and my spouse',
            ]]} />
            </${Field}>
        `
        : null}
      <${FormError} error=${save.error} shown=${['name', 'builtOn', 'inputs.beneficiary']} />
    </${Dialog}>
  `;
}
