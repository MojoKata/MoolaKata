// A 529 plan's parts of its account page (requirements S1.8): the plan's fields (shared by New
// account and Settings), its facts on the Overview, and the Contributions, Withdrawals and Goal
// tabs.
import { useState } from 'preact/hooks';
import { html } from '../app/html.js';
import { api } from '../api/client.js';
import { useApi, useList, useSubmit } from '../app/hooks.js';
import { date, money, today } from '../kit/format.js';
import { Amt } from '../kit/amount.js';
import { Empty, Failed, Loading } from '../kit/bits.js';
import { Field, ReadValue, Select } from '../kit/fields.js';
import { Icon } from '../kit/icon.js';
import { toast } from '../kit/toast.js';
import { ACCEPT, ReceiptLinkRec, uploadAll } from './receipt.js';
import { FanChart } from '../charts/chart.js';
import { EducationAnswer } from '../screens/projections.js';
import { num } from '../kit/dec.js';
import { canAdd, READ_ONLY, Record, whyNotAdd } from '../app/draft.js';
import { FIELDS } from '../api/fields.js';
import { DraftDialog, DraftForm, RecField, saveNow, useDraft } from './draft-form.js';
import { openDialog } from '../kit/dialog.js';
import { useDialogGuide } from './help.js';
import { Action } from '../kit/state.js';

/** A 529's plan (S1.8.1), in its account's draft. */
export class EduPlanRec extends Record {
  /** @override */
  static prefix = 'EdPln';
  /** @override */
  static fields = FIELDS.EducationPlanRecord;
  /** @override */
  static defaults = {
    planState: null,
    planName: null,
    beneficiaryId: null,
    openedOn: null,
    stateDeduction: null,
  };
}

/** A person added from the plan's Beneficiary (S10.10.3), in Add a person's own draft. */
class Beneficiary extends Record {
  /** @override */
  static prefix = 'Persn';
  /** @override */
  static fields = FIELDS.PersonRecord;
  /** @override */
  static defaults = {
    sex: null,
    birthMonth: null,
    birthDay: null,
    birthYear: null,
    diedOn: null,
    private: false,
    differentPerson: false,
  };
}

/**
 * A person added from a list that chooses one (S12.15.7): over the dialog or the Settings form
 * that asked, saved with its own Save. Closes with what was saved.
 * @param {{ close: (v?: any) => void }} p
 */
function PersonDialog({ close }) {
  useDialogGuide('dialog-new-person');
  const f = useDraft((draft) => {
    draft.add(Beneficiary, { name: '' });
  });
  const rec = /** @type {Beneficiary | undefined} */ (f.draft?.records[0]);
  return html`
    <${DraftDialog} f=${f} title="Add a Person" close=${close} what="This person"
      label="Add the Person" done="Person added">
      ${rec
        ? html`
          <${RecField} rec=${rec} name="name" label="Their name" />
          <div class="row">
            <${RecField} rec=${rec} name="sex" label="Sex" options=${[
              ['', 'Choose…'],
              ['female', 'Female'],
              ['male', 'Male'],
            ]} />
            <${RecField} rec=${rec} name="birthYear" label="Year of birth" />
          </div>
        `
        : null}
    </${DraftDialog}>
  `;
}

/**
 * The plan's fields, bound to its record; "Add a person…" opens Add a person over the form,
 * and chooses the one it adds.
 * @param {{ rec: EduPlanRec }} p
 */
export function PlanFields({ rec }) {
  const people = useList('/persons');
  const list = /** @type {any[]} */ (people.data) || [];
  // While Add a person is open, the list shows the choice that opened it.
  const [making, setMaking] = useState(false);
  const pick = async (/** @type {string} */ v) => {
    if (v !== 'new') return rec.input('beneficiaryId', v);
    setMaking(true);
    const saved = await openDialog(PersonDialog, {});
    setMaking(false);
    const made = saved?.find?.((/** @type {any} */ x) => x.entity === 'Persn')?.record;
    if (!made) return;
    people.reload();
    rec.input('beneficiaryId', made.id);
  };
  return html`
    <div class="row">
      <${RecField} rec=${rec} name="planState" label="Plan state" id="plan-state" />
      <${RecField} rec=${rec} name="planName" label="Plan name" id="plan-name" />
    </div>
    <${Field} label="Beneficiary" error=${rec.error('beneficiaryId')}>
      <${Select} value=${making ? 'new' : rec.get('beneficiaryId') || ''} onChange=${pick}
        options=${[
          ['', 'Choose…'],
          ...list.map((p) => [p.id, p.name]),
          ['new', 'Add a person…'],
        ]} />
      </${Field}>
      <div class="row">
        <${RecField} rec=${rec} name="openedOn" label="Opened" id="opened-on" type="date" />
        <${RecField} rec=${rec} name="stateDeduction" label="State tax deduction a year"
          id="state-deduction" />
      </div>
  `;
}

/**
 * The plan's record for a 529's draft: as stored, or a new one made only once it is edited.
 * @param {import('../app/draft.js').Draft} draft @param {string} accountId
 */
export async function loadPlan(draft, accountId) {
  const v = await api.get(`/accounts/${accountId}/plan529`);
  if (v.id) return draft.load(EduPlanRec, { ...v, accountId });
  return draft.add(EduPlanRec, { accountId }, { optional: true });
}

/**
 * The Settings card with the plan, in the account's Settings draft.
 * @param {{ rec: EduPlanRec }} p
 */
export function PlanCard({ rec }) {
  return html`
    <div class="card">
      <h3>The Plan</h3>
      <${PlanFields} rec=${rec} />
    </div>
  `;
}

/** The plan's facts on the Overview. */
/** @param {{ a: any }} p */
export function PlanFacts({ a }) {
  const res = useApi(`/accounts/${a.id}/plan529`, {}, ['import']);
  const v = /** @type {any} */ (res.data);
  if (!v) {
    return html`
      <div class="card">
        <${Loading} lines=${4} />
      </div>
    `;
  }
  const b = v.beneficiary;
  const r = v.rollover;
  return html`
    <div class="card facts">
      <h3>The Plan</h3>
      <div class="list-item"><span class="grow dim">Beneficiary</span>${b
        ? html`${b.name}${
          b.birthYear ? html`<span class="small dim"> · born ${b.birthYear}</span>` : null
        }`
        : html`<span class="dim">not chosen</span>`}</div>
      <div class="list-item"><span class="grow dim">Plan</span>${[v.planName, v.planState]
        .filter(Boolean).join(' · ') || '—'}</div>
      <div class="list-item"><span class="grow dim">Opened</span>${v.openedOn
        ? html`${date(v.openedOn)}${
          r.possibleFrom
            ? html`<span class="small dim"> · Roth rollover from ${date(r.possibleFrom)}</span>`
            : null
        }`
        : '—'}</div>
      <div class="list-item"><span class="grow dim">Contributed this year</span><${Amt}
        v=${v.contributedThisYear} cents=${false} /></div>
      <div class="list-item"><span class="grow dim">Owner</span>${a.ownerName}</div>
    </div>
  `;
}

/** @param {{ a: any }} p */
export function Contributions({ a }) {
  const res = useApi(`/accounts/${a.id}/contributions`, {}, ['import']);
  const plan = useApi(`/accounts/${a.id}/plan529`, {}, ['import']);
  const v = /** @type {any} */ (res.data);
  const pl = /** @type {any} */ (plan.data);
  if (res.error || plan.error) return html`<${Failed} error=${res.error || plan.error} />`;
  if (!v || !pl) return html`<${Loading} />`;
  const again = () => {
    res.reload();
    plan.reload();
  };
  const r = pl.rollover;
  // A contribution is a deposit made into the account: a transaction of it.
  const contributes = canAdd('Txn', a);
  return html`
    ${contributes ? html`<${AddContribution} a=${a} done=${again} />` : html`
      <div class="toolbar">
        <${Action} class="btn sm" why=${whyNotAdd('Txn', a)}><${Icon}
              name="plus" /> Record a Contribution</${Action}></div>
    `}
    <div class="card mt" style=${{ padding: '4px 8px' }}>
      <h3 style=${{ padding: '8px 8px 0' }}>Against the Annual Gift Exclusion</h3>
      ${v.years.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Contributions by contributor and year</caption>
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Contributor</th>
                  <th class="num">Counts</th>
                  <th class="num">Exclusion</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>${v.years.map((/** @type {any} */ y) =>
                html`
                  <tr>
                    <td>${y.year}</td>
                    <td>${y.name}${y.fromElection
                      ? html`<div class="small dim">a fifth of the ${y.fromElection} five-year
                election</div>`
                      : null}</td>
                    <td class="num">
                      <${Amt} v=${y.counted} cents=${false} />
                    </td>
                    <td class="num">
                      <${Amt} v=${y.exclusion} cents=${false} />
                    </td>
                    <td>${y.over ? html`<span class="pill warn">over: Form 709</span>` : null}</td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        `
        : html`<${Empty}>No contributions yet</${Empty}>`}
    </div>
    <div class="card mt" style=${{ padding: '4px 8px' }}>
      <h3 style=${{ padding: '8px 8px 0' }}>Contributions</h3>
      ${v.rows.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Contributions</caption>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>From</th>
                  <th class="num">Amount</th>
                </tr>
              </thead>
              <tbody>${v.rows.map((/** @type {any} */ c) =>
                html`
                  <tr>
                    <td>${date(c.date)}</td>
                    <td>
                      <div class="retag"><${Retag} a=${a} c=${c}
                                    done=${again} />${c.relationship
                                      ? html`<span class="small dim">${c.relationship}</span>`
                                      : null}${c.fiveYear
                                      ? html`<span class="pill info">five-year election</span>`
                                      : null}</div>
                    </td>
                    <td class="num">
                      <${Amt} v=${c.amount} />
                    </td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        `
        : null}
    </div>
    <div class="grid g2 mt">
      <div class="card facts">
        <h3>State Tax Deduction</h3>
        <div class="list-item"><span class="grow dim">Expected a year</span>${pl.stateDeduction
          ? html`<${Amt} v=${pl.stateDeduction} cents=${false} />`
          : '—'}</div>
      </div>
      <div class="card facts">
        <h3>Rollover to a Roth IRA</h3>
        <div class="list-item"><span class="grow dim">Possible from</span>${r.possibleFrom
          ? date(r.possibleFrom)
          : 'once the opening date is set'}</div>
        <div class="list-item"><span class="grow dim">Lifetime limit</span><span><${Amt}
          v=${r.limit} cents=${false} /><span class="small dim"> · used <${Amt} v=${r.used}
            cents=${false} /></span></span></div>
        <div class="list-item"><span class="grow dim">Could still roll over</span><${Amt}
          v=${r.available} cents=${false} /></div>
      </div>
    </div>
  `;
}

/** A contribution's tag (S1.8.2): who made a deposit, and the five-year election. */
class ContribRec extends Record {
  /** @override */
  static prefix = 'Cntrb';
  /** @override */
  static fields = FIELDS.ContributionRecord;
  /** @override */
  static defaults = { transactionId: null, fromAccountId: null, fiveYear: false };
}

/** @param {{ a: any, done: () => void }} p */
function AddContribution({ a, done }) {
  const people = useList('/persons');
  const accounts = useList('/accounts');
  const banks = (/** @type {any[]} */ (accounts.data) || []).filter((x) =>
    x.group === 'banking' && !x.closedOn && canAdd('Txn', x)
  );
  const f = useDraft((draft) => {
    draft.add(ContribRec, { accountId: a.id, date: today(), contributor: 'owner' });
  }, [a.id]);
  const rec = /** @type {ContribRec | undefined} */ (f.draft?.records[0]);
  return html`
    <${DraftForm} f=${f} class="card" where="the contribution" what="This contribution"
      label="Record" saved=${() => {
        toast('Contribution recorded');
        f.reload();
        done();
      }}>
      <h3>Record a Contribution</h3>
      ${rec
        ? html`
          <div class="row">
            <${RecField} rec=${rec} name="date" label="Date" type="date" />
            <${RecField} rec=${rec} name="amount" label="Amount" />
            <${RecField} rec=${rec} name="contributor" label="From" id="contributor"
              options=${[
                ['owner', 'You'],
                ...(/** @type {any[]} */ (people.data) || []).map((
                  p,
                ) => [`person:${p.id}`, p.name]),
              ]} />
            <${RecField} rec=${rec} name="fromAccountId" label="Paid from" id="from-account"
              options=${[['', 'Not recorded here'], ...banks.map((b) => [b.id, b.name])]} />
          </div>
          <${RecField} rec=${rec} name="fiveYear" label="Five-year election" />
        `
        : null}
    </${DraftForm}>
  `;
}

/**
 * Who an existing deposit came from: its tag made, or changed, at once; read, who it is
 * (S12.18.6).
 * @param {{ a: any, c: any, done: () => void }} p
 */
function Retag({ a, c, done }) {
  const people = useList('/persons');
  const save = useSubmit(async (/** @type {string} */ who) => {
    await saveNow((d) => {
      if (c.id) {
        d.load(ContribRec, { ...c, accountId: a.id, date: null, amount: null }).set(
          'contributor',
          who,
        );
      } else {
        d.add(ContribRec, {
          accountId: a.id,
          transactionId: c.transactionId,
          contributor: who,
          fiveYear: c.fiveYear,
        });
      }
    });
    toast('Saved');
    done();
  });
  const label = `Who the ${date(c.date)} contribution was from`;
  if (!a.access.writable) {
    return html`<${ReadValue} aria-label=${label} data-help="from" text=${c.name || '—'} />`;
  }
  return html`
    <${Select} aria-label=${label} data-help="from" value=${c.contributor}
      onChange=${(/** @type {string} */ v) => save.run(v).catch((e) => toast(e.message))}
      options=${[
        ['owner', a.ownerName],
        ...(/** @type {any[]} */ (people.data) || []).map((p) => [`person:${p.id}`, p.name]),
      ]} />
  `;
}

/** @param {{ a: any }} p */
export function Withdrawals({ a }) {
  const res = useApi(`/accounts/${a.id}/withdrawals`, {}, ['import']);
  const v = /** @type {any} */ (res.data);
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} />`;
  return html`
    <div class="card" style=${{ padding: '4px 8px' }}>
      <h3 style=${{ padding: '8px 8px 0' }}>Each Year</h3>
      ${v.years.length
        ? html`
          <div class="table-wrap">
            <table class="t">
              <caption class="sr-only">Distributions against qualified expenses</caption>
              <thead>
                <tr>
                  <th>Year</th>
                  <th class="num">Distributions</th>
                  <th class="num">Qualified Expenses</th>
                  <th class="num">Not Covered</th>
                </tr>
              </thead>
              <tbody>${v.years.map((/** @type {any} */ y) =>
                html`
                  <tr>
                    <td>${y.year}</td>
                    <td class="num">
                      <${Amt} v=${y.distributions} />
                    </td>
                    <td class="num">
                      <${Amt} v=${y.expenses} />
                    </td>
                    <td class="num">${num(
                        y.notCovered,
                      )
                      ? html`<span class="pill warn"><${Amt} v=${y.notCovered} /></span>`
                      : html`<span class="dim">—</span>`}</td>
                  </tr>
                `
              )}</tbody>
            </table>
          </div>
        `
        : html`<${Empty}>No withdrawals yet</${Empty}>`}
    </div>
    ${canAdd('QExpn', a)
      ? html`<${AddExpense} a=${a} kinds=${v.kinds} done=${res.reload} />`
      : html`
        <div class="toolbar mt">
          <${Action} class="btn sm" why=${whyNotAdd('QExpn', a)}><${Icon}
                name="plus" /> Add a Qualified Expense</${Action}></div>
      `}
    ${v.expenses.length
      ? html`<div class="card mt"><h3>Qualified Expenses</h3>${
        v.expenses.map((
          /** @type {any} */ x,
        ) => html`<${Expense} x=${x} canWrite=${a.access.writable} done=${res.reload} />`)
      }</div>`
      : null}
  `;
}

/** A qualified expense (S1.8.3) in its 529. */
class ExpenseRec extends Record {
  /** @override */
  static prefix = 'QExpn';
  /** @override */
  static fields = FIELDS.ExpenseRecord;
  /** @override */
  static defaults = { year: null, description: null };
}

/** @param {{ a: any, kinds: [string, string][], done: () => void }} p */
function AddExpense({ a, kinds, done }) {
  const f = useDraft((draft) => {
    draft.add(ExpenseRec, { accountId: a.id, date: today(), kind: 'tuition' });
  }, [a.id]);
  const rec = /** @type {ExpenseRec | undefined} */ (f.draft?.records[0]);
  return html`
    <${DraftForm} f=${f} class="card mt" where="the expense" what="This expense" label="Add"
      saved=${() => {
        toast('Expense added');
        f.reload();
        done();
      }}>
      <h3>Add a Qualified Expense</h3>
      ${rec
        ? html`
          <div class="row">
            <${RecField} rec=${rec} name="date" label="Paid on" id="paid-on" type="date" />
            <${RecField} rec=${rec} name="kind" label="Kind" options=${kinds} />
            <${RecField} rec=${rec} name="amount" label="Amount" />
          </div>
          <${RecField} rec=${rec} name="description" label="Description" />
        `
        : null}
    </${DraftForm}>
  `;
}

/** @param {{ x: any, canWrite: boolean, done: () => void }} p */
function Expense({ x, canWrite, done }) {
  const [busy, setBusy] = useState(false);
  const send = async (/** @type {FileList} */ files) => {
    setBusy(true);
    try {
      const made = await uploadAll(files);
      // Kept with the expense as its receipts, each a link saved at once (S1.8.3, S9.3).
      await saveNow((d) => {
        for (const r of made) {
          if (x.documents.some((/** @type {any} */ y) => y.id === r.id)) continue;
          d.add(ReceiptLinkRec, { receiptId: r.id, kind: 'expense', itemId: x.id });
        }
      });
    } catch (e) {
      toast(/** @type {any} */ (e).message);
    } finally {
      setBusy(false);
    }
    done();
  };
  const remove = useSubmit(async () => {
    await saveNow((d) => d.remove(d.load(ExpenseRec, x)));
    toast('Expense removed');
    done();
  });
  const fid = `f-expense-files-${x.id}`;
  return html`
    <div class="list-item"><div class="grow">${x.description || x.kindLabel}<div
      class="small dim">${x.kindLabel} · ${date(x.date)}${x.year !== Number(x.date.slice(0, 4))
        ? ` · counts in ${x.year}`
        : ''}${x.documents.length
        ? html`${' '}· <${Icon} name="clip" /> ${x.documents.length} receipt${
          x.documents.length === 1 ? '' : 's'
        }`
        : ''}</div></div><${Amt} v=${x.amount} />${!canWrite
        ? html`
          <${Action} class="btn sm"
            why=${READ_ONLY}><${Icon} name="clip" /> Receipt</${Action}><${Action}
                    class="icon-btn" why=${READ_ONLY} aria-label=${'Remove ' +
                      (x.description || x.kindLabel)}><${Icon} name="x" /></${Action}>
        `
        : html`
          <label class="btn sm" for=${fid}><${Icon} name="clip" /> ${busy
            ? 'Uploading…'
            : 'Receipt'}</label><input
            id=${fid} class="sr-only" type="file" multiple
            accept=${ACCEPT} data-help="receipts" onChange=${(/** @type {any} */ e) => {
              send(e.currentTarget.files);
              e.currentTarget.value = '';
            }} /><button type="button"
            class="icon-btn" aria-label=${'Remove ' +
              (x.description || x.kindLabel)} onClick=${() =>
              remove.run().catch(() => {})}><${Icon} name="x" /></button>
        `}</div>
  `;
}

/** @param {{ a: any }} p */
export function Goal({ a }) {
  const res = useApi(`/accounts/${a.id}/goal`, {}, ['import']);
  const v = /** @type {any} */ (res.data);
  const start = useSubmit(async () => {
    await api.post(`/accounts/${a.id}/goal`);
    toast('Education projection made');
    res.reload();
  });
  if (res.error) return html`<${Failed} error=${res.error} />`;
  if (!v) return html`<${Loading} />`;
  if (!v.beneficiary) {
    return html`<${Empty} action=${html`<a class="btn sm" href=${`/ui/accounts/${a.id}/settings`}>Settings</a>`}>No beneficiary chosen</${Empty}>`;
  }
  const x = v.projection;
  if (!x) {
    return html`<${Empty} action=${html`
      <button type="button" class="btn primary" disabled=${start.busy}
        onClick=${() => start.run().catch(() => {})}><${Icon} name="plus" /> Project ${v.beneficiary
          .name}'s
              Education</button>
    `}>No education projection yet</${Empty}>`;
  }
  const r = x.result;
  const ans = r.answer;
  return html`
    <div
      class="toolbar"><span class="small dim">Education projection <b>${x.name}</b>${x.active
        ? ' · active'
        : ' · a scenario'}</span>${x.status && x.status !== 'untracked'
        ? html`<span class="pill">${x.status}</span>`
        : null}<span class="spacer"></span><a class="small" href=${`/ui/projections/${x.id}`}>Change It in Projections</a></div>
    <div class="grid g-main">
      <div class="card">
        <h3>${ans.name}'s College Fund<span class="spacer"></span><span
        class=${'pill ' + (num(ans.funded) >= 100 ? 'ok' : 'warn')}>${Math.round(
          num(
            ans
              .funded,
          ),
        )}% funded</span></h3>
        <${FanChart} label=${`${x.name}: projected balance by year`} years=${r.years}
          p=${r.percentiles} marks=${[[ans.firstYear, 'school starts']]} />
        <p
          class="small dim">A model, not a forecast: ${ans.years} years from ${ans
            .firstYear}, each costing ${ans.costBasis === 'typed'
            ? 'the typed amount'
            : `the shipped ${ans.costBasis} average`} of ${money0(ans.costToday)} in today's
          dollars, rising ${r.assumptions.educationInflation}% a year.</p>
      </div>
      <div class="grid" style=${{ alignContent: 'start' }}>
        <${EducationAnswer} a=${ans} />
        <div class="card facts"><h3>Its Years</h3>${ans.costs.map((
          /** @type {number} */ c,
          /** @type {number} */ i,
        ) =>
          html`<div class="list-item"><span class="grow dim">${ans.firstYear + i}</span>${
            money0(
              c,
            )
          }</div>`
        )}</div>
      </div>
    </div>
  `;
}

/** @param {number} v */
function money0(v) {
  return money(String(Math.round(num(v))), { cents: false });
}
